# -*- mode: python ; coding: utf-8 -*-
# 文件夹打包（onedir：启动快、杀软误报少）：
#   uv run pyinstaller main.spec --noconfirm
#   → dist/urdf-inspector/urdf-inspector.exe（依赖在 dist/urdf-inspector/urdf-inspector-lib/）

import os

from PyInstaller.utils.hooks import collect_all

# 图标可选：没有 assets/icon.ico 时也能打包（exe 用默认图标，程序内用 icons.py 画的回退图标）
_ICON_DATAS = [(p, 'assets') for p in ('assets/icon.ico', 'assets/icon.png') if os.path.isfile(p)]
_EXE_ICON = 'assets/icon.ico' if os.path.isfile('assets/icon.ico') else None

# mujoco 带原生 DLL + 插件目录；glfw 带 glfw3.dll，用 collect_all 收齐
mj_datas, mj_binaries, mj_hidden = collect_all('mujoco')
glfw_datas, glfw_binaries, glfw_hidden = collect_all('glfw')

# mujoco 4.x 拆成 mujoco-core / mujoco-studio 等几个发行包，全部装进同一个 mujoco/ 目录。
# 本工具只用核心绑定 + 经典离屏渲染（GLFW），Studio 界面、文档、头文件、测试数据等用不到，剔掉省约 25 MB。
_MJ_DROP = ('studio', 'doc', 'include', 'introspect', 'sysid', 'testdata', 'usd')


def _mj_keep_file(entry):
    """entry = (源文件, 目标目录)；目标目录在 mujoco/<_MJ_DROP>/ 下的、以及 *_test.py 不要。"""
    parts = entry[1].replace('\\', '/').split('/')
    if len(parts) >= 2 and parts[0] == 'mujoco' and parts[1] in _MJ_DROP:
        return False
    return not os.path.basename(entry[0]).endswith('_test.py')


def _mj_keep_module(name):
    parts = name.split('.')
    if len(parts) >= 2 and parts[1] in _MJ_DROP:
        return False
    return not parts[-1].endswith('_test')


mj_datas = [e for e in mj_datas if _mj_keep_file(e)]
mj_binaries = [e for e in mj_binaries if _mj_keep_file(e)]
mj_hidden = [m for m in mj_hidden if _mj_keep_module(m)]

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=mj_binaries + glfw_binaries,
    datas=_ICON_DATAS + mj_datas + glfw_datas,
    hiddenimports=mj_hidden + glfw_hidden + ['urdf_inspector'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # mujoco-studio 及其依赖：本工具不用（见上面 _MJ_DROP）
        'mujoco.studio', 'mujoco_studio_wasm', 'websockets',
        # 用不到的 Qt 模块，减小体积
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.Qt3DCore', 'PySide6.Qt3DRender',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtSensors', 'PySide6.QtLocation',
        'PySide6.QtSerialPort', 'PySide6.QtSerialBus', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtXml',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtUiTools',
        'PySide6.QtNetworkAuth', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech', 'PySide6.QtSpatialAudio', 'PySide6.QtHttpServer', 'PySide6.QtWebSockets',
        'PySide6.QtWebView', 'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets',
        'tkinter', 'matplotlib', 'IPython', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='urdf-inspector',
    icon=_EXE_ICON,
    contents_directory='urdf-inspector-lib',   # PyInstaller 6 默认 _internal；带应用名避免多个工具解压到同一目录时互相覆盖
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # Qt / mujoco 的 DLL 压缩后易出问题
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='urdf-inspector',
    strip=False,
    upx=False,
    upx_exclude=[],
)
