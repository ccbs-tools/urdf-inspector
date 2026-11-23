"""入口：python -m urdf_inspector [urdf]

顺序固定：先初始化日志，再 import mujoco / Qt 与业务模块，最后建 QApplication 和主窗口。
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    import platform

    from .log import logger, setup_logging

    log_file = setup_logging()

    # 先 mujoco 再 Qt（Windows 原生 DLL 加载顺序）
    import mujoco
    from PySide6 import QtCore, QtGui, QtWidgets

    from . import APP_NAME, ORG, __version__
    from .i18n import i18n
    from .icons import app_icon
    from .main_window import MainWindow

    parser = argparse.ArgumentParser(description="urdf inspector (MuJoCo off-screen + Qt)")
    parser.add_argument("urdf", nargs="?", help="可选：启动时加载的 .urdf 路径")
    args = parser.parse_args(argv)

    logger.info("=" * 60)
    logger.info(
        "{} v{} starting | python {} | PySide6 {} | mujoco {} | {} | frozen={}",
        APP_NAME, __version__, platform.python_version(), QtCore.__version__, mujoco.__version__,
        platform.platform(), bool(getattr(sys, "frozen", False)),
    )
    logger.info("log file: {}", log_file)
    logger.debug("argv: {}", sys.argv[1:] if argv is None else argv)

    # Windows：不用 Python 默认 AppID，任务栏才会显示本程序图标而不是 python.exe
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORG}.{APP_NAME}")
        except Exception as e:  # noqa: BLE001
            logger.warning("SetCurrentProcessExplicitAppUserModelID failed: {}", e)

    # 本工具不用 QOpenGLWidget（MuJoCo 离屏渲染后用 QPainter 贴图），所以不设置 QSurfaceFormat

    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName(ORG)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont("Microsoft YaHei UI", 9))
    i18n.load()                      # 读取上次选的语言（首次跟随系统），需在 QApplication 之后
    icon = app_icon()
    app.setWindowIcon(icon)

    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    if args.urdf:
        logger.info("initial file from argv: {}", args.urdf)
        win.load_urdf(args.urdf)
    code = app.exec()
    logger.info("exit code={}", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
