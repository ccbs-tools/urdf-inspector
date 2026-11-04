# -*- mode: python ; coding: utf-8 -*-
# 文件夹打包（onedir，启动快）：
#   uv run pyinstaller urdf_inspector.spec   →  dist/urdf-inspector/urdf-inspector.exe

from PyInstaller.utils.hooks import collect_all

# mujoco 带原生 DLL + 插件目录；glfw 带 glfw3.dll，用 collect_all 全部收进来
mj_datas, mj_binaries, mj_hidden = collect_all("mujoco")
glfw_datas, glfw_binaries, glfw_hidden = collect_all("glfw")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=mj_binaries + glfw_binaries,
    datas=mj_datas + glfw_datas,
    hiddenimports=mj_hidden + glfw_hidden + ["urdf_inspector"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 没用到的 Qt 模块，减小体积
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtXml",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtUiTools",
        "tkinter",
        "matplotlib",
        "IPython",
        "pytest",
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
    name="urdf-inspector",
    contents_directory="urdf-inspector-lib",  # 依赖平铺到根目录，不生成 _internal
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # mujoco / Qt 的 DLL 压缩后容易出问题，关掉
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
    name="urdf-inspector",
    strip=False,
    upx=False,
    upx_exclude=[],
)
