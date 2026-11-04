"""主窗口：左选项/关节 · 中仿真 · 右 STL 预览/关节。"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

import mujoco
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .i18n import LANGUAGES, i18n, tr
from .model import BuiltModel, GeomInfo, ViewOptions, build_model
from .stl_view import StlPreview
from .viewport import Viewport

HL_VISUAL = np.array([0.15, 0.85, 1.0, 1.0], dtype=np.float64)
HL_COLLISION = np.array([1.0, 0.45, 0.08, 1.0], dtype=np.float64)
DIM_ALPHA = 0.12
ROLE_GEOM_ID = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1


class JointSlider(QWidget):
    """单个关节：名称 + 滑条 + 数值。"""

    def __init__(self, name: str, lo: float, hi: float, is_angle: bool, parent=None) -> None:
        super().__init__(parent)
        self.name = name
        self.is_angle = is_angle
        self.lo = lo
        self.hi = hi
        self._block = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)

        row = QHBoxLayout()
        unit = "°" if is_angle else "m"
        self._title = QLabel(name)
        self._value = QLabel("0")
        self._value.setMinimumWidth(56)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._title)
        row.addStretch(1)
        row.addWidget(self._value)
        row.addWidget(QLabel(unit))
        lay.addLayout(row)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        lay.addWidget(self.slider)
        self.slider.valueChanged.connect(self._on_slider)

    def set_callback(self, cb) -> None:
        self._cb = cb

    def _on_slider(self, v: int) -> None:
        if self._block:
            return
        t = v / 1000.0
        rad_or_m = self.lo + t * (self.hi - self.lo)
        self._update_label(rad_or_m)
        cb = getattr(self, "_cb", None)
        if cb:
            cb(self.name, rad_or_m)

    def _update_label(self, rad_or_m: float) -> None:
        if self.is_angle:
            self._value.setText(f"{math.degrees(rad_or_m):.1f}")
        else:
            self._value.setText(f"{rad_or_m:.4f}")

    def set_value(self, rad_or_m: float, *, emit: bool = False) -> None:
        rad_or_m = max(self.lo, min(self.hi, float(rad_or_m)))
        t = 0.0 if self.hi <= self.lo else (rad_or_m - self.lo) / (self.hi - self.lo)
        self._block = True
        self.slider.setValue(int(round(t * 1000)))
        self._update_label(rad_or_m)
        self._block = False
        if emit:
            cb = getattr(self, "_cb", None)
            if cb:
                cb(self.name, rad_or_m)

    def value(self) -> float:
        t = self.slider.value() / 1000.0
        return self.lo + t * (self.hi - self.lo)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1000, 800)

        self._urdf: Optional[Path] = None
        self._built: Optional[BuiltModel] = None
        self._opts = ViewOptions()
        self._sliders: Dict[str, JointSlider] = {}
        self._physics = True
        self._highlight_ids: Set[int] = set()
        self._geom_by_id: Dict[int, GeomInfo] = {}
        self._stl_loaded: Optional[Path] = None

        self.viewport = Viewport()
        self.viewport.urdfDropped.connect(self.load_urdf)
        self.stl_preview = StlPreview()
        self.stl_preview.statusMessage.connect(self.statusBar().showMessage)

        left = self._build_left_panel()
        right = self._build_right_panel()

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 700])
        self.setCentralWidget(split)

        self._build_menu()
        i18n.languageChanged.connect(self.retranslate)
        self.retranslate()

    def closeEvent(self, ev) -> None:
        self.viewport.shutdown()
        self.stl_preview.shutdown()
        super().closeEvent(ev)

    def _build_menu(self) -> None:
        self.menu_file = self.menuBar().addMenu("")
        self.act_open = QAction(self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._browse)
        self.menu_file.addAction(self.act_open)
        self.act_reload = QAction(self)
        self.act_reload.setShortcut(QKeySequence.StandardKey.Refresh)
        self.act_reload.triggered.connect(self._reload)
        self.menu_file.addAction(self.act_reload)
        self.menu_file.addSeparator()
        self.act_quit = QAction(self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)
        self.menu_file.addAction(self.act_quit)

        self.menu_view = self.menuBar().addMenu("")
        self.act_reset_sim = QAction(self)
        self.act_reset_sim.triggered.connect(self.viewport.reset_view)
        self.menu_view.addAction(self.act_reset_sim)
        self.act_reset_stl = QAction(self)
        self.act_reset_stl.triggered.connect(self.stl_preview.reset_view)
        self.menu_view.addAction(self.act_reset_stl)
        self.act_home = QAction(self)
        self.act_home.setShortcut(Qt.Key.Key_Backspace)
        self.act_home.triggered.connect(self._reset_joints)
        self.menu_view.addAction(self.act_home)

        # 语言菜单：各语言用自己的名字显示，不随当前语言翻译
        self.menu_lang = self.menuBar().addMenu("")
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)
        for code, label in LANGUAGES:
            act = QAction(label, self, checkable=True)
            act.setData(code)
            act.setChecked(code == i18n.lang)
            act.triggered.connect(lambda _=False, c=code: i18n.set(c))
            self.lang_group.addAction(act)
            self.menu_lang.addAction(act)

    def retranslate(self) -> None:
        self.menu_file.setTitle(tr("menu.file"))
        self.act_open.setText(tr("menu.open"))
        self.act_reload.setText(tr("menu.reload"))
        self.act_quit.setText(tr("menu.quit"))
        self.menu_view.setTitle(tr("menu.view"))
        self.act_reset_sim.setText(tr("menu.reset_sim_cam"))
        self.act_reset_stl.setText(tr("menu.reset_stl_cam"))
        self.act_home.setText(tr("menu.home_joints"))
        self.menu_lang.setTitle(tr("menu.language"))
        for act in self.lang_group.actions():
            act.setChecked(act.data() == i18n.lang)

        self.opts_box.setTitle(tr("opts.box"))
        self.chk_collision.setText(tr("opts.collision"))
        self.chk_gravity.setText(tr("opts.gravity"))
        self.chk_color.setText(tr("opts.color"))
        self.chk_com.setText(tr("opts.com"))
        self.chk_frames.setText(tr("opts.frames"))
        self.chk_world.setText(tr("opts.world"))
        self.chk_physics.setText(tr("opts.physics"))
        self.lbl_alpha.setText(tr("opts.alpha"))
        self.btn_apply.setText(tr("opts.apply"))
        self.btn_home.setText(tr("opts.home"))
        self.geom_box.setTitle(tr("geom.box"))
        self.btn_clear_hl.setText(tr("geom.clear_hl"))
        self.btn_expand.setText(tr("geom.expand"))
        self.btn_collapse.setText(tr("geom.collapse"))
        self.geom_tip.setText(tr("geom.tip"))
        self.joints_box.setTitle(tr("joints.box"))

        self._update_title()
        if self._urdf is None:
            self._path_label.setText(tr("path.none"))
            self.statusBar().showMessage(tr("status.drop_hint"))
        elif self._built is not None:
            self.statusBar().showMessage(
                tr("status.loaded", name=self._urdf.name, n=len(self._built.joints))
            )

    def _update_title(self) -> None:
        if self._urdf is None:
            self.setWindowTitle(tr("app.title"))
        else:
            self.setWindowTitle(f"{tr('app.title')} — {self._urdf.name}")

    def _build_left_panel(self) -> QWidget:
        """左栏：显示选项 / 连杆几何 / 关节控制，整体放在一个竖向滚动区里。"""
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(8, 8, 8, 8)

        self.opts_box = QGroupBox()
        opts_lay = QVBoxLayout(self.opts_box)

        self.chk_collision = QCheckBox()
        self.chk_gravity = QCheckBox()
        self.chk_gravity.setChecked(True)
        self.chk_color = QCheckBox()
        self.chk_com = QCheckBox()
        self.chk_frames = QCheckBox()
        self.chk_world = QCheckBox()
        self.chk_world.setChecked(True)
        self.chk_physics = QCheckBox()
        self.chk_physics.setChecked(True)

        for w in (
            self.chk_collision,
            self.chk_gravity,
            self.chk_color,
            self.chk_com,
            self.chk_frames,
            self.chk_world,
            self.chk_physics,
        ):
            opts_lay.addWidget(w)

        alpha_row = QHBoxLayout()
        self.lbl_alpha = QLabel()
        alpha_row.addWidget(self.lbl_alpha)
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.05, 1.0)
        self.spin_alpha.setSingleStep(0.05)
        self.spin_alpha.setValue(1.0)
        self.spin_alpha.setDecimals(2)
        alpha_row.addWidget(self.spin_alpha)
        opts_lay.addLayout(alpha_row)

        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton()
        self.btn_apply.clicked.connect(self._apply_options)
        btn_row.addWidget(self.btn_apply)
        self.btn_home = QPushButton()
        self.btn_home.clicked.connect(self._reset_joints)
        btn_row.addWidget(self.btn_home)
        opts_lay.addLayout(btn_row)

        for w in (
            self.chk_collision,
            self.chk_gravity,
            self.chk_color,
            self.chk_com,
            self.chk_frames,
            self.chk_world,
        ):
            w.toggled.connect(lambda _=False: self._apply_options())
        self.spin_alpha.valueChanged.connect(lambda _=0.0: self._apply_options())
        self.chk_physics.toggled.connect(self._on_physics)

        root.addWidget(self.opts_box)

        self.geom_box = QGroupBox()
        geom_lay = QVBoxLayout(self.geom_box)
        self.geom_tree = QTreeWidget()
        self.geom_tree.setHeaderHidden(True)
        self.geom_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.geom_tree.setUniformRowHeights(True)
        self.geom_tree.setMinimumHeight(320)
        self.geom_tree.itemSelectionChanged.connect(self._on_geom_selection)
        geom_lay.addWidget(self.geom_tree)

        geom_btns = QHBoxLayout()
        self.btn_clear_hl = QPushButton()
        self.btn_clear_hl.clicked.connect(self._clear_highlight)
        self.btn_expand = QPushButton()
        self.btn_expand.clicked.connect(self.geom_tree.expandAll)
        self.btn_collapse = QPushButton()
        self.btn_collapse.clicked.connect(self.geom_tree.collapseAll)
        geom_btns.addWidget(self.btn_clear_hl)
        geom_btns.addWidget(self.btn_expand)
        geom_btns.addWidget(self.btn_collapse)
        geom_lay.addLayout(geom_btns)

        self.geom_tip = QLabel()
        self.geom_tip.setWordWrap(True)
        self.geom_tip.setStyleSheet("color: #90a4ae; font-size: 11px;")
        # 自动换行的 QLabel 最小宽度提示会很大，导致滚动区内容被横向裁切；忽略其宽度要求
        self.geom_tip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        geom_lay.addWidget(self.geom_tip)
        root.addWidget(self.geom_box)

        self.joints_box = QGroupBox()
        self._joints_lay = QVBoxLayout(self.joints_box)
        self._joints_lay.addStretch(1)
        root.addWidget(self.joints_box)

        self._path_label = QLabel()
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color: #78909c; font-size: 11px;")
        self._path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self._path_label)
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(340)
        return scroll

    def _build_right_panel(self) -> QWidget:
        """右栏：上 URDF 仿真，下 STL 预览，中间留一条可拖动的间隙。"""
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.viewport)
        split.addWidget(self.stl_preview)
        split.setHandleWidth(6)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([500, 330])
        return split

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dialog.open_title"), "", tr("dialog.open_filter")
        )
        if path:
            self.load_urdf(path)

    def _reload(self) -> None:
        if self._urdf:
            self.load_urdf(str(self._urdf))

    def _collect_opts(self) -> ViewOptions:
        return ViewOptions(
            show_collision=self.chk_collision.isChecked(),
            gravity=self.chk_gravity.isChecked(),
            color_joints=self.chk_color.isChecked(),
            show_com=self.chk_com.isChecked(),
            show_frames=self.chk_frames.isChecked(),
            world_frame=self.chk_world.isChecked(),
            alpha=float(self.spin_alpha.value()),
        )

    def _apply_options(self) -> None:
        if not self._urdf:
            return
        q_keep = self._snapshot_joints()
        self._opts = self._collect_opts()
        try:
            built = build_model(self._urdf, self._opts)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("dialog.rebuild_fail"), str(exc))
            return
        self._install_built(built, q_keep=q_keep)

    def _on_physics(self, on: bool) -> None:
        self._physics = on
        self.viewport.set_physics(on)

    def load_urdf(self, path: str) -> None:
        urdf = Path(path)
        if not urdf.is_file():
            QMessageBox.warning(self, tr("dialog.no_file"), path)
            return
        self._opts = self._collect_opts()
        try:
            built = build_model(urdf, self._opts)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("dialog.load_fail"), str(exc))
            return
        self._urdf = urdf
        self._install_built(built)
        self._update_title()
        self._path_label.setText(str(urdf))
        self.statusBar().showMessage(
            tr("status.loaded", name=urdf.name, n=len(built.joints))
        )

    def _snapshot_joints(self) -> Dict[str, float]:
        return {name: sl.value() for name, sl in self._sliders.items()}

    def _clear_joint_layout(self, lay: QVBoxLayout) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        lay.addStretch(1)

    def _install_built(self, built: BuiltModel, q_keep: Optional[Dict[str, float]] = None) -> None:
        prev_keys = self._selected_geom_keys()
        self._built = built
        self._geom_by_id = {g.geom_id: g for g in built.geoms}
        self._sliders.clear()
        self._clear_joint_layout(self._joints_lay)
        self._rebuild_geom_tree(built)

        for info in built.joints:
            q0 = float(built.data.qpos[info.qposadr])
            if q_keep and info.name in q_keep:
                q0 = q_keep[info.name]
            sl = JointSlider(info.name, info.range[0], info.range[1], info.is_angle)
            sl.set_callback(self._on_joint)
            self._joints_lay.insertWidget(self._joints_lay.count() - 1, sl)
            self._sliders[info.name] = sl
            sl.set_value(q0)
            self._write_ctrl(info.name, q0)

        self.viewport.set_model(built.model, built.data, physics=self._physics)
        mujoco.mj_forward(built.model, built.data)
        if prev_keys:
            self._reselect_geom_keys(prev_keys)
        else:
            self._highlight_ids.clear()
            self._apply_highlight()
            self.stl_preview.clear()
            self._stl_loaded = None
        self.viewport.mark_dirty()

    def _geom_key(self, g: GeomInfo) -> tuple:
        return (g.body_name, g.kind, g.label)

    def _selected_geom_keys(self) -> Set[tuple]:
        keys: Set[tuple] = set()
        for gid in self._highlight_ids:
            g = self._geom_by_id.get(gid)
            if g:
                keys.add(self._geom_key(g))
        return keys

    def _rebuild_geom_tree(self, built: BuiltModel) -> None:
        self.geom_tree.blockSignals(True)
        self.geom_tree.clear()
        body_order: List[str] = []
        by_body: Dict[str, List[GeomInfo]] = defaultdict(list)
        for g in built.geoms:
            if g.body_name not in by_body:
                body_order.append(g.body_name)
            by_body[g.body_name].append(g)

        brush_v = QBrush(QColor("#4fc3f7"))
        brush_c = QBrush(QColor("#ff9800"))

        for body_name in body_order:
            visuals = [g for g in by_body[body_name] if g.kind == "visual"]
            colls = [g for g in by_body[body_name] if g.kind == "collision"]
            if not visuals and not colls:
                continue
            body_item = QTreeWidgetItem([f"{body_name}  ({len(visuals)}v/{len(colls)}c)"])
            body_item.setFlags(body_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.geom_tree.addTopLevelItem(body_item)

            if visuals:
                v_root = QTreeWidgetItem(["visual"])
                v_root.setForeground(0, brush_v)
                v_root.setFlags(v_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                body_item.addChild(v_root)
                for g in visuals:
                    it = QTreeWidgetItem([g.label])
                    it.setData(0, ROLE_GEOM_ID, g.geom_id)
                    it.setData(0, ROLE_KIND, g.kind)
                    tip = f"id={g.geom_id}"
                    if g.mesh_path:
                        tip += f"\n{g.mesh_path}"
                    it.setToolTip(0, tip)
                    v_root.addChild(it)

            if colls:
                c_root = QTreeWidgetItem(["collision"])
                c_root.setForeground(0, brush_c)
                c_root.setFlags(c_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                body_item.addChild(c_root)
                for g in colls:
                    it = QTreeWidgetItem([g.label])
                    it.setData(0, ROLE_GEOM_ID, g.geom_id)
                    it.setData(0, ROLE_KIND, g.kind)
                    tip = f"id={g.geom_id}"
                    if g.mesh_path:
                        tip += f"\n{g.mesh_path}"
                    it.setToolTip(0, tip)
                    c_root.addChild(it)

        self.geom_tree.expandToDepth(1)
        self.geom_tree.blockSignals(False)

    def _reselect_geom_keys(self, keys: Set[tuple]) -> None:
        self.geom_tree.blockSignals(True)
        self.geom_tree.clearSelection()
        for i in range(self.geom_tree.topLevelItemCount()):
            body = self.geom_tree.topLevelItem(i)
            for j in range(body.childCount()):
                kind_node = body.child(j)
                for k in range(kind_node.childCount()):
                    leaf = kind_node.child(k)
                    gid = leaf.data(0, ROLE_GEOM_ID)
                    g = self._geom_by_id.get(gid)
                    if g and self._geom_key(g) in keys:
                        leaf.setSelected(True)
        self.geom_tree.blockSignals(False)
        self._on_geom_selection()

    def _on_geom_selection(self) -> None:
        ids: Set[int] = set()
        for it in self.geom_tree.selectedItems():
            gid = it.data(0, ROLE_GEOM_ID)
            if gid is not None:
                ids.add(int(gid))
        self._highlight_ids = ids
        self._apply_highlight()
        self._update_stl_preview()

    def _clear_highlight(self) -> None:
        self.geom_tree.clearSelection()
        self._highlight_ids.clear()
        self._apply_highlight()
        self.stl_preview.clear()
        self._stl_loaded = None

    def _update_stl_preview(self) -> None:
        # 多选时用最后选中的带 mesh 的项
        path: Optional[Path] = None
        for it in self.geom_tree.selectedItems():
            gid = it.data(0, ROLE_GEOM_ID)
            if gid is None:
                continue
            g = self._geom_by_id.get(int(gid))
            if g and g.mesh_path:
                path = g.mesh_path
        if path is None:
            if self._highlight_ids:
                self.stl_preview.clear(tr("stl.no_mesh"))
            else:
                self.stl_preview.clear()
            self._stl_loaded = None
            return
        if not path.is_file():
            self.stl_preview.clear(tr("stl.not_found", path=path))
            self._stl_loaded = None
            return
        if self._stl_loaded == path:
            return
        if self.stl_preview.load(path):
            self._stl_loaded = path

    def _apply_highlight(self) -> None:
        if self._built is None or self._built.rgba_base is None or self._built.group_base is None:
            return
        model = self._built.model
        model.geom_rgba[:] = self._built.rgba_base
        model.geom_group[:] = self._built.group_base
        if not self._highlight_ids:
            self.viewport.mark_dirty()
            return

        robot_ids = {g.geom_id for g in self._built.geoms}
        for i in robot_ids:
            if i in self._highlight_ids:
                continue
            model.geom_rgba[i, 3] = float(self._built.rgba_base[i, 3]) * DIM_ALPHA

        for gid in self._highlight_ids:
            g = self._geom_by_id.get(gid)
            if g is None:
                continue
            if g.kind == "collision":
                model.geom_group[gid] = 0
                model.geom_rgba[gid] = HL_COLLISION
            else:
                model.geom_rgba[gid] = HL_VISUAL
        self.viewport.mark_dirty()
        n = len(self._highlight_ids)
        self.statusBar().showMessage(tr("status.highlight", n=n))

    def _write_ctrl(self, name: str, value: float) -> None:
        if self._built is None:
            return
        model, data = self._built.model, self._built.data
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        if aid >= 0:
            data.ctrl[aid] = value
        if not self._physics:
            for info in self._built.joints:
                if info.name == name:
                    data.qpos[info.qposadr] = value
                    break
            mujoco.mj_forward(model, data)
        self.viewport.mark_dirty()

    def _on_joint(self, name: str, value: float) -> None:
        self._write_ctrl(name, value)

    def _reset_joints(self) -> None:
        if self._built is None:
            return
        model, data = self._built.model, self._built.data
        if model.nkey > 0:
            mujoco.mj_resetDataKeyframe(model, data, 0)
        else:
            mujoco.mj_resetData(model, data)
        for info in self._built.joints:
            q = float(data.qpos[info.qposadr])
            sl = self._sliders.get(info.name)
            if sl:
                sl.set_value(q)
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, info.name)
            if aid >= 0:
                data.ctrl[aid] = q
        mujoco.mj_forward(model, data)
        self.viewport.mark_dirty()
