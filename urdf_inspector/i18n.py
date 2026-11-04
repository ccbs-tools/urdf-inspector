"""界面文案的中英文切换。

用法：
    from .i18n import tr, i18n
    label.setText(tr("opts.box"))
    i18n.languageChanged.connect(self.retranslate)

语言保存在 QSettings（组织 CCBS / 程序 urdf inspector），首次运行默认英文。
"""

from __future__ import annotations

from PySide6 import QtCore

DEFAULT_LANG = "en"
LANGUAGES = (("en", "English"), ("zh", "中文（简体）"))
_SETTINGS_KEY = "language"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.title": "urdf inspector",
        "menu.file": "&File",
        "menu.open": "&Open URDF…",
        "menu.reload": "&Reload",
        "menu.quit": "&Quit",
        "menu.view": "&View",
        "menu.reset_sim_cam": "Reset sim camera",
        "menu.reset_stl_cam": "Reset STL camera",
        "menu.home_joints": "Home joints",
        "menu.language": "&Language",
        "status.drop_hint": "Drop a .urdf, or File → Open",
        "status.loaded": "Loaded {name}  ·  {n} controllable joints",
        "status.highlight": "Highlighted {n} geoms (Ctrl/Shift to multi-select)",
        "opts.box": "Display options",
        "opts.collision": "Show collision",
        "opts.gravity": "Gravity",
        "opts.color": "Color by joint",
        "opts.com": "Center of mass",
        "opts.frames": "Link frames",
        "opts.world": "World frame",
        "opts.physics": "Physics stepping",
        "opts.alpha": "Opacity α",
        "opts.apply": "Apply options",
        "opts.home": "Home joints",
        "geom.box": "Link geometry",
        "geom.clear_hl": "Clear highlight",
        "geom.expand": "Expand",
        "geom.collapse": "Collapse",
        "geom.tip": "Pick a visual / collision: it is highlighted in the sim and its STL "
        "is previewed below-right (origin XYZ). Highlight temporarily overrides color/opacity.",
        "joints.box": "Joint control",
        "path.none": "Not loaded",
        "dialog.open_title": "Open URDF",
        "dialog.open_filter": "URDF (*.urdf);;All (*.*)",
        "dialog.rebuild_fail": "Rebuild failed",
        "dialog.no_file": "File not found",
        "dialog.load_fail": "Load failed",
        "stl.no_mesh": "Selected geom has no mesh file\n(may be a primitive shape)",
        "stl.not_found": "File not found\n{path}",
        "stl.hint": "Pick a visual / collision in \"Link geometry\" on the left\nto view its STL",
        "stl.load_fail_box": "Load failed\n{name}\n{err}",
        "stl.load_fail_status": "STL load failed: {err}",
        "stl.render_err": "STL preview render error: {err}",
        "stl.tips": "LMB rotate  RMB pan  Wheel zoom  Double-click/R reset  "
        "F fit  W wireframe  G grid  A axes    grid {step}",
    },
    "zh": {
        "app.title": "urdf inspector",
        "menu.file": "文件(&F)",
        "menu.open": "打开 URDF…(&O)",
        "menu.reload": "重新加载(&R)",
        "menu.quit": "退出(&Q)",
        "menu.view": "视图(&V)",
        "menu.reset_sim_cam": "复位仿真相机",
        "menu.reset_stl_cam": "复位 STL 相机",
        "menu.home_joints": "复位关节 (Home)",
        "menu.language": "语言(&L)",
        "status.drop_hint": "拖入 .urdf，或 文件 → 打开",
        "status.loaded": "已加载 {name}  ·  {n} 可控关节",
        "status.highlight": "高亮 {n} 个几何体（Ctrl/Shift 多选）",
        "opts.box": "显示选项",
        "opts.collision": "显示碰撞体",
        "opts.gravity": "重力",
        "opts.color": "按关节染色",
        "opts.com": "质心",
        "opts.frames": "连杆坐标系",
        "opts.world": "世界坐标系",
        "opts.physics": "物理步进",
        "opts.alpha": "透明度 α",
        "opts.apply": "应用选项",
        "opts.home": "复位关节",
        "geom.box": "连杆几何",
        "geom.clear_hl": "清除高亮",
        "geom.expand": "展开",
        "geom.collapse": "折叠",
        "geom.tip": "点选 visual / collision：仿真中高亮，右下预览对应 STL（原点 XYZ）。"
        "高亮会临时覆盖染色/透明度。",
        "joints.box": "关节控制",
        "path.none": "未加载",
        "dialog.open_title": "打开 URDF",
        "dialog.open_filter": "URDF (*.urdf);;所有文件 (*.*)",
        "dialog.rebuild_fail": "重建失败",
        "dialog.no_file": "文件不存在",
        "dialog.load_fail": "加载失败",
        "stl.no_mesh": "选中的几何没有 mesh 文件\n（可能是基本形状）",
        "stl.not_found": "找不到文件\n{path}",
        "stl.hint": "在左侧「连杆几何」里选 visual / collision\n查看对应 STL",
        "stl.load_fail_box": "加载失败\n{name}\n{err}",
        "stl.load_fail_status": "STL 加载失败：{err}",
        "stl.render_err": "STL 预览渲染出错：{err}",
        "stl.tips": "左键旋转  右键平移  滚轮缩放  双击/R 复位  "
        "F 适配  W 线框  G 网格  A 坐标轴    网格 {step}",
    },
}


class _I18n(QtCore.QObject):
    languageChanged = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lang = DEFAULT_LANG

    @property
    def lang(self) -> str:
        return self._lang

    def load(self) -> str:
        """从 QSettings 读取上次选择的语言；需在 QApplication 创建后调用。"""
        saved = QtCore.QSettings().value(_SETTINGS_KEY, DEFAULT_LANG)
        self._lang = saved if saved in _STRINGS else DEFAULT_LANG
        return self._lang

    def set(self, lang: str) -> None:
        if lang not in _STRINGS or lang == self._lang:
            return
        self._lang = lang
        QtCore.QSettings().setValue(_SETTINGS_KEY, lang)
        self.languageChanged.emit(lang)

    def tr(self, key: str, **kwargs) -> str:
        table = _STRINGS.get(self._lang, {})
        text = table.get(key) or _STRINGS[DEFAULT_LANG].get(key) or key
        return text.format(**kwargs) if kwargs else text


i18n = _I18n()


def tr(key: str, **kwargs) -> str:
    return i18n.tr(key, **kwargs)
