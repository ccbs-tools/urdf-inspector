"""入口：python -m urdf_inspector [urdf]"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    # 先 mujoco 再 Qt（Windows DLL 顺序）
    import mujoco  # noqa: F401
    from PySide6.QtWidgets import QApplication

    from .i18n import i18n
    from .main_window import MainWindow

    parser = argparse.ArgumentParser(description="urdf inspector (MuJoCo off-screen + Qt)")
    parser.add_argument("urdf", nargs="?", help="可选：启动时加载的 .urdf 路径")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setOrganizationName("CCBS")
    app.setApplicationName("urdf inspector")
    i18n.load()  # 读取上次选的语言（首次默认英文）
    win = MainWindow()
    win.show()
    if args.urdf:
        win.load_urdf(args.urdf)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
