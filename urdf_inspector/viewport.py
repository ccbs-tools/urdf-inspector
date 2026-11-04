"""MuJoCo 离屏渲染的 Qt 视口：拖放 URDF、鼠标轨道相机。"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

# 先 mujoco 再 Qt，避免 Windows 上插件 DLL 顺序问题
import mujoco
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QOpenGLContext,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


def release_qt_gl_context() -> None:
    """MuJoCo 渲染会把自己的 GLFW 上下文设为当前；Qt 仍以为自己的上下文是当前的，
    之后 QOpenGLWidget 会跳过 makeCurrent 而画到错误的上下文。这里主动让 Qt
    的上下文 doneCurrent，使下一次绘制重新 makeCurrent。"""
    ctx = QOpenGLContext.currentContext()
    if ctx is not None:
        ctx.doneCurrent()


def close_renderer(renderer) -> None:
    """安全关闭 mujoco.Renderer。

    Renderer.close() 释放 mjrContext 时直接删 GL 对象，但不会先切回自己的 GL 上下文；
    若此时当前上下文属于另一个 Renderer（程序里有两个视口），会把对方的纹理 / FBO
    删掉，导致对方黑屏。所以先 make_current 再 close。"""
    if renderer is None:
        return
    try:
        gl = getattr(renderer, "_gl_context", None)
        if gl is not None:
            gl.make_current()
    except Exception:  # noqa: BLE001
        pass
    try:
        renderer.close()
    except Exception:  # noqa: BLE001
        pass
    release_qt_gl_context()


class Viewport(QWidget):
    """自绘 3D 区。发出 urdfDropped(path)。"""

    urdfDropped = Signal(str)
    FPS = 30

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)

        self.model: Optional[mujoco.MjModel] = None
        self.data: Optional[mujoco.MjData] = None
        self.renderer = None
        self.cam: Optional[mujoco.MjvCamera] = None
        self.opt: Optional[mujoco.MjvOption] = None
        self.error = "把 .urdf 文件拖到这里，或用菜单 / 打开"
        self.hint = "左键旋转  右键平移  滚轮缩放  双击复位"
        self._img: Optional[QImage] = None
        self._buf: Optional[np.ndarray] = None
        self._dirty = True
        self._last_pos = QPoint()
        self._w = 0
        self._h = 0
        self._step_physics = False
        self._render_failures = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / self.FPS))

    def set_model(self, model: mujoco.MjModel, data: mujoco.MjData, *, physics: bool = False) -> None:
        close_renderer(self.renderer)
        self.renderer = None
        self._render_failures = 0
        self.model = model
        self.data = data
        self._step_physics = physics
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.reset_view()
        self.opt = mujoco.MjvOption()
        self.opt.geomgroup[3] = 0  # 碰撞体 group 3 默认不画（除非加载时已并入 visual）
        self.error = ""
        self._dirty = True
        self.update()

    def clear(self, message: str = "") -> None:
        self.model = None
        self.data = None
        self.renderer = None
        self.cam = None
        self._img = None
        self.error = message or "把 .urdf 文件拖到这里"
        self.update()

    def mark_dirty(self) -> None:
        self._dirty = True

    def shutdown(self) -> None:
        """窗口关闭前释放 MuJoCo 渲染器（否则 Qt 先销毁 GL 环境，GLFW 退出时报警告）。"""
        self._timer.stop()
        close_renderer(self.renderer)
        self.renderer = None

    def set_physics(self, on: bool) -> None:
        self._step_physics = on

    def reset_view(self) -> None:
        if self.cam is None:
            return
        self.cam.lookat[:] = [0.0, 0.0, 0.25]
        self.cam.distance = 1.4
        self.cam.azimuth = 135.0
        self.cam.elevation = -22.0
        self._dirty = True

    def _ensure_renderer(self) -> None:
        assert self.model is not None
        w = max(64, min(self.width(), 1920))
        h = max(64, min(self.height(), 1200))
        if self.renderer is not None and (w, h) == (self._w, self._h):
            return
        close_renderer(self.renderer)
        self.renderer = None
        self.renderer = mujoco.Renderer(self.model, height=h, width=w)
        release_qt_gl_context()
        self._w, self._h = w, h
        self._dirty = True

    def _tick(self) -> None:
        if self.model is None or self.data is None or not self.isVisible():
            return
        if self._step_physics:
            mujoco.mj_step(self.model, self.data)
            self._dirty = True
        if not self._dirty:
            return
        try:
            self._ensure_renderer()
            self.renderer.update_scene(self.data, self.cam, self.opt)
            self.renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
            rgb = self.renderer.render()
            release_qt_gl_context()
            self._buf = np.ascontiguousarray(rgb)
            h, w, _ = self._buf.shape
            self._img = QImage(self._buf.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            # 不直接丢模型：先重建渲染器重试几次，仍失败才放弃
            self._render_failures += 1
            close_renderer(self.renderer)
            self.renderer = None
            if self._render_failures >= 3:
                self.error = f"渲染出错：{exc}"
                self.model = None
            else:
                self._dirty = True
        self.update()

    def resizeEvent(self, ev) -> None:
        self._dirty = True
        super().resizeEvent(ev)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._img is not None and self.model is not None:
            p.drawImage(self.rect(), self._img)
        if self.error:
            p.setPen(QPen(QColor("#ffb74d")))
            p.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.error,
            )
        # 左下角操作提示：半透明底色，浅色地面上也能看清
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self.hint)
        th = fm.height()
        bg = self.rect().adjusted(6, 0, 0, -6)
        bg.setTop(bg.bottom() - th - 6)
        bg.setRight(bg.left() + tw + 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(bg, 4, 4)
        p.setPen(QPen(QColor("#e0e0e0")))
        p.drawText(bg, Qt.AlignmentFlag.AlignCenter, self.hint)
        p.end()

    def _camera_basis(self):
        """MuJoCo 自由相机的 (forward, right, up)。"""
        az = math.radians(self.cam.azimuth)
        el = math.radians(self.cam.elevation)
        fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        n = np.linalg.norm(right)
        right = right / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        up = np.cross(right, fwd)
        return fwd, right, up

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasUrls():
            for u in ev.mimeData().urls():
                if u.toLocalFile().lower().endswith(".urdf"):
                    ev.acceptProposedAction()
                    return
        ev.ignore()

    def dropEvent(self, ev: QDropEvent) -> None:
        for u in ev.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(".urdf"):
                self.urdfDropped.emit(path)
                ev.acceptProposedAction()
                return
        ev.ignore()

    def mousePressEvent(self, ev) -> None:
        self._last_pos = ev.pos()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.reset_view()

    def mouseMoveEvent(self, ev) -> None:
        if self.cam is None:
            return
        d = ev.pos() - self._last_pos
        self._last_pos = ev.pos()
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self.cam.azimuth = (self.cam.azimuth - d.x() * 0.4) % 360.0
            self.cam.elevation = max(-89.0, min(89.0, self.cam.elevation - d.y() * 0.4))
            self._dirty = True
        elif ev.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
            _, right, up = self._camera_basis()
            fovy = float(self.model.vis.global_.fovy) if self.model is not None else 45.0
            per_px = 2 * self.cam.distance * math.tan(math.radians(fovy) / 2) / max(self.height(), 1)
            look = np.asarray(self.cam.lookat) - right * d.x() * per_px + up * d.y() * per_px
            self.cam.lookat[:] = look
            self._dirty = True

    def wheelEvent(self, ev) -> None:
        if self.cam is None:
            return
        steps = ev.angleDelta().y() / 120.0
        self.cam.distance = float(max(0.2, min(8.0, self.cam.distance * (0.9 ** steps))))
        self._dirty = True
