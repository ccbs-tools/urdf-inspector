"""界面文案的中英文切换。

用法：
    from .i18n import tr, i18n
    label.setText(tr("opts.box"))
    i18n.languageChanged.connect(self.retranslate)

语言保存在 QSettings（组织 ORG / 应用 APP_NAME，见 __init__.py）。首次运行跟随系统：系统是中文 → zh，否则 → en。
新增文案：两张表各加一条，键名用 `模块.含义`。
"""

from __future__ import annotations

from PySide6 import QtCore

from .log import logger

LANGUAGES = (("en", "English"), ("zh", "中文（简体）"))
_FALLBACK_LANG = "en"
_SETTINGS_KEY = "language"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.title": "urdf inspector",
        "menu.file": "&File",
        "menu.open": "&Open URDF / MJCF…",
        "menu.reload": "&Reload",
        "menu.quit": "&Quit",
        "menu.view": "&View",
        "menu.reset_sim_cam": "Reset sim camera",
        "menu.reset_stl_cam": "Reset STL camera",
        "menu.home_joints": "Home joints",
        "menu.language": "&Language",
        "menu.help": "&Help",
        "menu.repo": "&Repository Homepage",
        "menu.video": "&Video Tutorial",
        "menu.changelog": "Version &Info",
        "menu.check_update": "Check for &Updates",
        "menu.open_log_dir": "Open &Log Folder",
        "chg.title": "Version info  (current v{ver})",
        "chg.check": "Check for updates",
        "chg.close": "Close",
        "upd.title": "Check for updates",
        "upd.checking": "Checking for updates…",
        "upd.countdown": "{sec} s",
        "upd.cancel": "Cancel",
        "upd.close": "Close",
        "upd.download": "Download",
        "upd.latest": "You are on the latest version (v{cur}).",
        "upd.newer": "New version v{latest} available (current v{cur}).",
        "upd.failed_short": "Check failed. Please check your network and try again.",
        "upd.timeout": "No response within {sec} s. Check your network and try again.",
        "status.drop_hint": "Drop a .urdf or MJCF .xml, or File → Open",
        "status.loaded": "Loaded {name}  ·  {n} controllable joints",
        "status.loaded_view": "Loaded {name}  ·  MJCF, view only  ·  {n} geoms",
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
        "joints.view_only": "MJCF files are view-only: the model is loaded as-is, "
        "without joint sliders or physics stepping.",
        "path.none": "Not loaded",
        "dialog.open_title": "Open URDF / MJCF",
        "dialog.open_filter": "Robot models (*.urdf *.xml);;URDF (*.urdf);;MJCF (*.xml);;All (*.*)",
        "dialog.rebuild_fail": "Rebuild failed",
        "dialog.no_file": "File not found",
        "dialog.load_fail": "Load failed",
        "dialog.err_fragment": "This file is an MJCF fragment (root element \"mujocoinclude\") "
        "and cannot be loaded on its own.\nOpen the main file that includes it instead.",
        "dialog.err_unknown_root": "Unrecognized root element \"{tag}\".\n"
        "Expected \"robot\" (URDF) or \"mujoco\" (MJCF).",
        "dialog.err_bad_xml": "Not a valid XML file:\n{err}",
        "stl.no_mesh": "Selected geom has no mesh file\n(may be a primitive shape)",
        "stl.not_found": "File not found\n{path}",
        "stl.hint": "Pick a visual / collision in \"Link geometry\" on the left\nto view its STL",
        "stl.load_fail_box": "Load failed\n{name}\n{err}",
        "stl.load_fail_status": "STL load failed: {err}",
        "stl.render_err": "STL preview render error: {err}",
        "stl.tips": "LMB rotate  RMB pan  Wheel zoom  Double-click/R reset  "
        "F fit  W wireframe  G grid  A axes    grid {step}",
        "view.drop_hint": "Drop a .urdf or MJCF .xml file here, or use File → Open",
        "view.hint": "LMB rotate  RMB pan  Wheel zoom  Double-click reset",
        "view.render_err": "Render error: {err}",
    },
    "zh": {
        "app.title": "urdf inspector",
        "menu.file": "文件(&F)",
        "menu.open": "打开 URDF / MJCF…(&O)",
        "menu.reload": "重新加载(&R)",
        "menu.quit": "退出(&Q)",
        "menu.view": "视图(&V)",
        "menu.reset_sim_cam": "复位仿真相机",
        "menu.reset_stl_cam": "复位 STL 相机",
        "menu.home_joints": "复位关节 (Home)",
        "menu.language": "语言(&L)",
        "menu.help": "帮助(&H)",
        "menu.repo": "仓库主页(&R)",
        "menu.video": "视频教程(&V)",
        "menu.changelog": "版本介绍(&I)",
        "menu.check_update": "检查更新(&U)",
        "menu.open_log_dir": "打开日志目录(&L)",
        "chg.title": "版本介绍（当前 v{ver}）",
        "chg.check": "检查版本更新",
        "chg.close": "关闭",
        "upd.title": "检查版本更新",
        "upd.checking": "正在检查更新…",
        "upd.countdown": "{sec} 秒",
        "upd.cancel": "取消",
        "upd.close": "关闭",
        "upd.download": "下载",
        "upd.latest": "已是最新版本（v{cur}）。",
        "upd.newer": "发现新版本 v{latest}（当前 v{cur}）。",
        "upd.failed_short": "检查失败，请检查网络后重试。",
        "upd.timeout": "{sec} 秒内没有响应，请检查网络后重试。",
        "status.drop_hint": "拖入 .urdf 或 MJCF 的 .xml，或 文件 → 打开",
        "status.loaded": "已加载 {name}  ·  {n} 可控关节",
        "status.loaded_view": "已加载 {name}  ·  MJCF 只看模式  ·  {n} 个几何体",
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
        "joints.view_only": "MJCF 文件为只看模式：模型原样加载，不提供关节滑条和物理步进。",
        "path.none": "未加载",
        "dialog.open_title": "打开 URDF / MJCF",
        "dialog.open_filter": "机器人模型 (*.urdf *.xml);;URDF (*.urdf);;MJCF (*.xml);;所有文件 (*.*)",
        "dialog.rebuild_fail": "重建失败",
        "dialog.no_file": "文件不存在",
        "dialog.load_fail": "加载失败",
        "dialog.err_fragment": "这个文件是 MJCF 片段（根标签为 \"mujocoinclude\"），不能单独加载。\n"
        "请打开引用它的主文件。",
        "dialog.err_unknown_root": "无法识别的根标签 \"{tag}\"。\n"
        "需要 \"robot\"（URDF）或 \"mujoco\"（MJCF）。",
        "dialog.err_bad_xml": "不是有效的 XML 文件：\n{err}",
        "stl.no_mesh": "选中的几何没有 mesh 文件\n（可能是基本形状）",
        "stl.not_found": "找不到文件\n{path}",
        "stl.hint": "在左侧「连杆几何」里选 visual / collision\n查看对应 STL",
        "stl.load_fail_box": "加载失败\n{name}\n{err}",
        "stl.load_fail_status": "STL 加载失败：{err}",
        "stl.render_err": "STL 预览渲染出错：{err}",
        "stl.tips": "左键旋转  右键平移  滚轮缩放  双击/R 复位  "
        "F 适配  W 线框  G 网格  A 坐标轴    网格 {step}",
        "view.drop_hint": "把 .urdf 或 MJCF 的 .xml 文件拖到这里，或用菜单 文件 → 打开",
        "view.hint": "左键旋转  右键平移  滚轮缩放  双击复位",
        "view.render_err": "渲染出错：{err}",
    },
}


def _system_default() -> str:
    return "zh" if QtCore.QLocale.system().language() == QtCore.QLocale.Language.Chinese else "en"


class _I18n(QtCore.QObject):
    languageChanged = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lang = _FALLBACK_LANG

    @property
    def lang(self) -> str:
        return self._lang

    def load(self) -> str:
        """从 QSettings 读取上次选择的语言；需在 QApplication 创建后调用。"""
        saved = QtCore.QSettings().value(_SETTINGS_KEY)
        self._lang = saved if saved in _STRINGS else _system_default()
        logger.info("language: {} (saved={!r}, system={})", self._lang, saved, QtCore.QLocale.system().name())
        return self._lang

    def set(self, lang: str) -> None:
        if lang not in _STRINGS or lang == self._lang:
            return
        logger.info("language switched {} -> {}", self._lang, lang)
        self._lang = lang
        QtCore.QSettings().setValue(_SETTINGS_KEY, lang)
        self.languageChanged.emit(lang)

    def tr(self, key: str, **kwargs) -> str:
        table = _STRINGS.get(self._lang, {})
        text = table.get(key) or _STRINGS[_FALLBACK_LANG].get(key) or key
        return text.format(**kwargs) if kwargs else text


i18n = _I18n()


def tr(key: str, **kwargs) -> str:
    return i18n.tr(key, **kwargs)


__all__ = ["LANGUAGES", "i18n", "tr"]
