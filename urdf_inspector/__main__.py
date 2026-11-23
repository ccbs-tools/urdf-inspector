"""入口：python -m urdf_inspector [urdf]"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    import platform

    from .log import logger, setup_logging

    log_file = setup_logging()

    # 先 mujoco 再 Qt（Windows DLL 顺序）
    import mujoco  # noqa: F401
    from PySide6 import QtCore
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .i18n import i18n
    from .main_window import MainWindow, make_app_icon

    parser = argparse.ArgumentParser(description="urdf inspector (MuJoCo off-screen + Qt)")
    parser.add_argument("urdf", nargs="?", help="可选：启动时加载的 .urdf 路径")
    args = parser.parse_args(argv)

    logger.info("=" * 60)
    logger.info(
        "urdf-inspector v{} 启动 | python {} | PySide6 {} | mujoco {} | {} | frozen={}",
        __version__, platform.python_version(), QtCore.__version__, mujoco.__version__,
        platform.platform(), bool(getattr(sys, "frozen", False)),
    )
    logger.info("日志文件: {}", log_file)
    logger.debug("argv: {}", sys.argv[1:] if argv is None else argv)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.ccbs.urdf_inspector"
            )
        except Exception:  # noqa: BLE001
            pass

    app = QApplication(sys.argv)
    app.setOrganizationName("CCBS")
    app.setApplicationName("urdf inspector")
    icon = make_app_icon()
    app.setWindowIcon(icon)
    i18n.load()  # 读取上次选的语言（首次默认英文）
    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    if args.urdf:
        logger.info("命令行指定启动文件: {}", args.urdf)
        win.load_urdf(args.urdf)
    code = app.exec()
    logger.info("程序退出 code={}", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
