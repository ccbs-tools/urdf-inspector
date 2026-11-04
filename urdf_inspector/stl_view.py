"""STL 预览：MuJoCo 离屏渲染（与仿真视口同一套 GL），显示网格 + 原点 XYZ 轴 + 地面网格。

不用 QOpenGLWidget：Qt 自己的 GL 会和 MuJoCo 的 GLFW 上下文互抢，导致黑屏。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

import mujoco
import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .i18n import i18n, tr
from .meshio import load_mesh
from .viewport import close_renderer, release_qt_gl_context

AXIS_COLORS = {"X": (0.92, 0.20, 0.20), "Y": (0.20, 0.80, 0.20), "Z": (0.25, 0.45, 1.00)}
AXIS_DIRS = {
    "X": np.array([1.0, 0.0, 0.0]),
    "Y": np.array([0.0, 1.0, 0.0]),
    "Z": np.array([0.0, 0.0, 1.0]),
}
# 把 z 轴圆柱转到 x / y / z 方向的四元数 (w, x, y, z)
AXIS_QUATS = {
    "X": [0.7071068, 0.0, 0.7071068, 0.0],
    "Y": [0.7071068, -0.7071068, 0.0, 0.0],
    "Z": [1.0, 0.0, 0.0, 0.0],
}
MESH_RGBA = [0.72, 0.76, 0.80, 1.0]
BG_TOP = [0.18, 0.20, 0.24]
BG_BOTTOM = [0.06, 0.07, 0.09]


class StlPreview(QWidget):
    """只读 STL 预览：原点坐标系 + 转台相机，MuJoCo 离屏渲染。"""

    statusMessage = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.path: Optional[Path] = None
        self.model: Optional[mujoco.MjModel] = None
        self.data: Optional[mujoco.MjData] = None
        self.renderer = None
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.opt = mujoco.MjvOption()

        self.bbox_min = np.zeros(3)
        self.bbox_max = np.zeros(3)
        self.n_faces = 0
        self.title = ""
        self._hint: Optional[str] = None  # None 表示用当前语言的默认提示
        i18n.languageChanged.connect(self.update)

        self.axis_len = 1.0
        self.grid_step = 0.1
        self.grid_half = 1.0
        self.show_axes = True
        self.show_grid = True
        self.wireframe = False
        self._home: Optional[Tuple[float, float, float, np.ndarray]] = None

        self._img: Optional[QImage] = None
        self._buf: Optional[np.ndarray] = None
        self._dirty = True
        self._w = 0
        self._h = 0
        self._last_pos = QPoint()
        self._button = None

    # ------------------------------------------------------------------ 加载
    def clear(self, hint: str = "") -> None:
        self._free_renderer()
        self.path = None
        self.model = None
        self.data = None
        self._img = None
        self.title = ""
        self._hint = hint or None
        self.update()

    def load(self, path: Path | str) -> bool:
        path = Path(path)
        try:
            verts, faces = load_mesh(path)
            lo, hi, n_faces = verts.min(axis=0), verts.max(axis=0), len(faces)
            model = self._build_model(verts, faces, lo, hi)
        except Exception as exc:  # noqa: BLE001
            self.clear(tr("stl.load_fail_box", name=path.name, err=exc))
            self.statusMessage.emit(tr("stl.load_fail_status", err=exc))
            return False

        self._free_renderer()
        self.path = path
        self.bbox_min, self.bbox_max, self.n_faces = lo, hi, n_faces
        self.model = model
        self.data = mujoco.MjData(model)
        mujoco.mj_forward(model, self.data)
        ext = hi - lo
        unit = "mm?" if ext.max() > 5.0 else "m"
        self.title = (
            f"{path.name}  ·  {n_faces:,} faces  ·  "
            f"{ext[0]:.4g} × {ext[1]:.4g} × {ext[2]:.4g} ({unit})"
        )
        self.cam.azimuth = 225.0
        self.cam.elevation = -25.0
        self.fit_view(remember_home=True)
        self.statusMessage.emit(self.title)
        self._dirty = True
        self.update()
        return True

    def _update_scale(self) -> None:
        ext = float((self.bbox_max - self.bbox_min).max())
        far = float(np.abs(np.concatenate([self.bbox_min, self.bbox_max])).max())
        self.axis_len = max(ext, far) * 0.6 if ext > 0 else 1.0
        span = max(ext, far) * 1.5 or 1.0
        mag = 10 ** math.floor(math.log10(max(span / 10, 1e-12)))
        self.grid_step = mag
        for k in (1, 2, 5, 10):
            if span / (k * mag) <= 12:
                self.grid_step = k * mag
                break
        self.grid_half = self.grid_step * math.ceil(span / self.grid_step)

    def _build_model(
        self, verts: np.ndarray, faces: np.ndarray, lo: np.ndarray, hi: np.ndarray
    ) -> mujoco.MjModel:
        self.bbox_min, self.bbox_max = lo, hi
        self._update_scale()
        L = self.axis_len
        r = max(L * 0.012, 1e-6)

        spec = mujoco.MjSpec()
        spec.modelname = "stl_preview"

        sky = spec.add_texture()
        sky.name = "sky"
        sky.type = mujoco.mjtTexture.mjTEXTURE_SKYBOX
        sky.builtin = mujoco.mjtBuiltin.mjBUILTIN_GRADIENT
        sky.rgb1 = BG_TOP
        sky.rgb2 = BG_BOTTOM
        sky.width = 256
        sky.height = 256

        spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
        spec.visual.headlight.diffuse = [0.75, 0.75, 0.75]
        spec.visual.headlight.specular = [0.25, 0.25, 0.25]
        spec.visual.global_.offwidth = 1920
        spec.visual.global_.offheight = 1200
        spec.visual.map.znear = 0.002
        spec.visual.map.zfar = 100.0

        mesh = spec.add_mesh()
        mesh.name = "stl"
        # 直接注入顶点 / 面，不让 MuJoCo 自己开文件（中文路径会失败）
        mesh.uservert = verts.reshape(-1).tolist()
        mesh.userface = faces.reshape(-1).tolist()
        try:
            mesh.inertia = mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL
        except Exception:  # noqa: BLE001
            pass

        body = spec.worldbody
        g = body.add_geom()
        g.name = "stl"
        g.type = mujoco.mjtGeom.mjGEOM_MESH
        g.meshname = "stl"
        g.rgba = MESH_RGBA
        g.contype, g.conaffinity = 0, 0

        for axis, d in AXIS_DIRS.items():
            c = AXIS_COLORS[axis]
            pos_axis = body.add_geom()
            pos_axis.name = f"axis_{axis}"
            pos_axis.type = mujoco.mjtGeom.mjGEOM_CYLINDER
            pos_axis.size = [r, L / 2, 0.0]
            pos_axis.pos = (d * L / 2).tolist()
            pos_axis.quat = AXIS_QUATS[axis]
            pos_axis.rgba = [c[0], c[1], c[2], 1.0]
            pos_axis.contype, pos_axis.conaffinity = 0, 0

            neg_axis = body.add_geom()
            neg_axis.name = f"axis_{axis}_neg"
            neg_axis.type = mujoco.mjtGeom.mjGEOM_CYLINDER
            neg_axis.size = [r * 0.4, L / 4, 0.0]
            neg_axis.pos = (-d * L / 4).tolist()
            neg_axis.quat = AXIS_QUATS[axis]
            neg_axis.rgba = [c[0], c[1], c[2], 0.35]
            neg_axis.contype, neg_axis.conaffinity = 0, 0

        origin = body.add_geom()
        origin.name = "origin"
        origin.type = mujoco.mjtGeom.mjGEOM_SPHERE
        origin.size = [r * 2.2, 0.0, 0.0]
        origin.rgba = [1.0, 1.0, 1.0, 1.0]
        origin.contype, origin.conaffinity = 0, 0

        model = spec.compile()
        span = max(float((hi - lo).max()), float(np.abs(np.concatenate([lo, hi])).max()), 1e-6)
        model.stat.extent = span * 2.0
        model.stat.center[:] = (np.minimum(lo, 0) + np.maximum(hi, 0)) / 2
        return model

    # ------------------------------------------------------------------ 相机
    def fit_view(self, remember_home: bool = False) -> None:
        if self.model is None:
            return
        lo = np.minimum(self.bbox_min, 0.0)
        hi = np.maximum(self.bbox_max, 0.0)
        center = (lo + hi) / 2
        radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
        fovy = float(self.model.vis.global_.fovy)
        self.cam.lookat[:] = center
        self.cam.distance = radius / math.sin(math.radians(fovy) / 2) * 1.05
        if remember_home:
            self._home = (self.cam.azimuth, self.cam.elevation, self.cam.distance, center.copy())
        self._dirty = True
        self.update()

    def reset_view(self) -> None:
        if self._home is None:
            self.cam.azimuth, self.cam.elevation = 225.0, -25.0
            self.fit_view(remember_home=True)
            return
        az, el, dist, look = self._home
        self.cam.azimuth, self.cam.elevation, self.cam.distance = az, el, dist
        self.cam.lookat[:] = look
        self._dirty = True
        self.update()

    def _camera_basis(self):
        """MuJoCo 自由相机：forward 指向 lookat。返回 (pos, forward, right, up)。"""
        az = math.radians(self.cam.azimuth)
        el = math.radians(self.cam.elevation)
        fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        pos = np.asarray(self.cam.lookat) - fwd * self.cam.distance
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        n = np.linalg.norm(right)
        right = right / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        up = np.cross(right, fwd)
        return pos, fwd, right, up

    def _project(self, p: np.ndarray) -> Optional[Tuple[float, float]]:
        if self.model is None:
            return None
        pos, fwd, right, up = self._camera_basis()
        d = p - pos
        cz = float(d @ fwd)
        if cz <= 1e-9:
            return None
        t = math.tan(math.radians(float(self.model.vis.global_.fovy)) / 2)
        w, h = max(self.width(), 1), max(self.height(), 1)
        aspect = w / h
        nx = float(d @ right) / (cz * t * aspect)
        ny = float(d @ up) / (cz * t)
        return ((nx + 1) / 2 * w, (1 - ny) / 2 * h)

    # ------------------------------------------------------------------ 鼠标键盘
    def mousePressEvent(self, e) -> None:
        self._last_pos = e.position().toPoint()
        self._button = e.button()

    def mouseReleaseEvent(self, e) -> None:
        self._button = None

    def mouseDoubleClickEvent(self, e) -> None:
        self.reset_view()

    def mouseMoveEvent(self, e) -> None:
        if self.model is None or self._button is None:
            return
        cur = e.position().toPoint()
        d = cur - self._last_pos
        self._last_pos = cur
        if self._button == Qt.MouseButton.LeftButton:
            self.cam.azimuth = (self.cam.azimuth - d.x() * 0.4) % 360.0
            self.cam.elevation = max(-89.0, min(89.0, self.cam.elevation - d.y() * 0.4))
        elif self._button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            _, _, right, up = self._camera_basis()
            fovy = float(self.model.vis.global_.fovy)
            per_px = 2 * self.cam.distance * math.tan(math.radians(fovy) / 2) / max(self.height(), 1)
            look = np.asarray(self.cam.lookat) - right * d.x() * per_px + up * d.y() * per_px
            self.cam.lookat[:] = look
        self._dirty = True
        self.update()

    def wheelEvent(self, e) -> None:
        if self.model is None:
            return
        steps = e.angleDelta().y() / 120.0
        self.cam.distance = float(max(self.cam.distance * (0.88 ** steps), 1e-5))
        self._dirty = True
        self.update()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_F:
            self.fit_view()
        elif k == Qt.Key.Key_R:
            self.reset_view()
        elif k == Qt.Key.Key_W:
            self.wireframe = not self.wireframe
        elif k == Qt.Key.Key_G:
            self.show_grid = not self.show_grid
        elif k == Qt.Key.Key_A:
            self.show_axes = not self.show_axes
        else:
            super().keyPressEvent(e)
            return
        self._dirty = True
        self.update()

    # ------------------------------------------------------------------ 渲染
    def _free_renderer(self) -> None:
        close_renderer(self.renderer)
        self.renderer = None

    def shutdown(self) -> None:
        self._free_renderer()

    def _ensure_renderer(self) -> None:
        assert self.model is not None
        w = max(64, min(self.width(), 1920))
        h = max(64, min(self.height(), 1200))
        if self.renderer is not None and (w, h) == (self._w, self._h):
            return
        self._free_renderer()
        self.renderer = mujoco.Renderer(self.model, height=h, width=w)
        release_qt_gl_context()
        self._w, self._h = w, h
        self._dirty = True

    def _add_line(self, scene, a, b, rgba, width: float) -> None:
        if scene.ngeom >= scene.maxgeom:
            return
        g = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            g,
            mujoco.mjtGeom.mjGEOM_LINE,
            np.zeros(3),
            np.zeros(3),
            np.eye(3).flatten(),
            np.asarray(rgba, dtype=np.float32),
        )
        mujoco.mjv_connector(
            g,
            mujoco.mjtGeom.mjGEOM_LINE,
            width,
            np.asarray(a, dtype=np.float64),
            np.asarray(b, dtype=np.float64),
        )
        scene.ngeom += 1

    def _add_grid(self, scene) -> None:
        n = int(round(self.grid_half / self.grid_step))
        if n > 60:
            n = 60
        half = n * self.grid_step
        for i in range(-n, n + 1):
            v = i * self.grid_step
            major = i % 5 == 0
            rgba = [0.55, 0.58, 0.62, 0.45 if major else 0.18]
            self._add_line(scene, [v, -half, 0], [v, half, 0], rgba, 1.0)
            self._add_line(scene, [-half, v, 0], [half, v, 0], rgba, 1.0)

    def _set_axes_visible(self, visible: bool) -> None:
        if self.model is None:
            return
        for i in range(self.model.ngeom):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
            if name.startswith("axis_") or name == "origin":
                self.model.geom_rgba[i, 3] = (
                    (0.35 if name.endswith("_neg") else 1.0) if visible else 0.0
                )

    def _render(self) -> None:
        if self.model is None or self.data is None:
            return
        try:
            self._ensure_renderer()
            self._set_axes_visible(self.show_axes)
            self.renderer.update_scene(self.data, self.cam, self.opt)
            scene = self.renderer.scene
            scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
            scene.flags[mujoco.mjtRndFlag.mjRND_WIREFRAME] = 1 if self.wireframe else 0
            if self.show_grid:
                self._add_grid(scene)
            rgb = self.renderer.render()
            release_qt_gl_context()
            self._buf = np.ascontiguousarray(rgb)
            h, w, _ = self._buf.shape
            self._img = QImage(self._buf.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            self.statusMessage.emit(tr("stl.render_err", err=exc))
            self._img = None
            self._dirty = False

    def resizeEvent(self, ev) -> None:
        self._dirty = True
        super().resizeEvent(ev)

    def paintEvent(self, ev) -> None:
        if self.model is not None and self._dirty:
            self._render()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor.fromRgbF(*BG_BOTTOM))
        if self._img is not None and self.model is not None:
            p.drawImage(self.rect(), self._img)

        font = p.font()
        if self.model is None:
            font.setPointSize(10)
            p.setFont(font)
            p.setPen(QColor(200, 200, 200, 200))
            p.drawText(
                self.rect().adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._hint or tr("stl.hint"),
            )
        else:
            # 轴标签
            if self.show_axes:
                font.setPointSize(10)
                font.setBold(True)
                p.setFont(font)
                for axis, d in AXIS_DIRS.items():
                    pt = self._project(d * self.axis_len * 1.08)
                    if pt is None:
                        continue
                    c = AXIS_COLORS[axis]
                    p.setPen(QColor.fromRgbF(*c))
                    p.drawText(QPointF(pt[0] - 5, pt[1] + 5), axis)
            self._draw_corner_triad(p)
            font.setBold(False)
            font.setPointSize(9)
            p.setFont(font)
            p.setPen(QColor(235, 235, 235))
            p.drawText(QPointF(8, 18), self.title)

        font.setBold(False)
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(QColor(170, 170, 170))
        p.drawText(
            QPointF(8, self.height() - 8),
            tr("stl.tips", step=f"{self.grid_step:g}"),
        )
        p.end()

    def _draw_corner_triad(self, p: QPainter) -> None:
        """右下角固定大小的小三轴，只反映当前朝向。"""
        _, _, right, up = self._camera_basis()
        size = 34.0
        cx = self.width() - size - 18
        cy = self.height() - size - 26
        font = p.font()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        for axis, d in AXIS_DIRS.items():
            x2 = float(d @ right) * size
            y2 = -float(d @ up) * size
            c = QColor.fromRgbF(*AXIS_COLORS[axis])
            pen = QPen(c)
            pen.setWidthF(2.5)
            p.setPen(pen)
            p.drawLine(QPointF(cx, cy), QPointF(cx + x2, cy + y2))
            p.drawText(QPointF(cx + x2 * 1.25 - 4, cy + y2 * 1.25 + 4), axis)
        p.setPen(QPen(QColor(255, 255, 255)))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
