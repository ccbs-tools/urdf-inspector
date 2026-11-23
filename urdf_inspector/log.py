"""日志（loguru）。

文件：~/.ccbs/urdf-inspector/app.log，单文件最大 10 MB，最多保留 3 个（含当前）。
用法：
    from .log import logger
    logger.info("...")
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path.home() / ".ccbs" / "urdf-inspector"
LOG_FILE = LOG_DIR / "app.log"
ROTATION = "10 MB"
RETENTION = 3

_FILE_FMT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | "
    "{name}:{function}:{line} | {message}"
)
_CONSOLE_FMT = (
    "<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | {message}"
)

_configured = False


def setup_logging(console_level: str = "INFO") -> Path:
    """初始化日志；重复调用只生效一次。返回日志文件路径。"""
    global _configured
    if _configured:
        return LOG_FILE
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    # PyInstaller --windowed 模式下 stderr 为 None，不能加控制台 sink
    if sys.stderr is not None:
        logger.add(sys.stderr, level=console_level, format=_CONSOLE_FMT, colorize=True)
    logger.add(
        LOG_FILE,
        level="DEBUG",
        format=_FILE_FMT,
        rotation=ROTATION,
        retention=RETENTION,
        encoding="utf-8",
        enqueue=True,          # 后台线程（检查更新）也能安全写
        backtrace=False,
        diagnose=False,
    )

    sys.excepthook = _excepthook
    _install_qt_handler()
    return LOG_FILE


def _excepthook(exc_type, exc, tb) -> None:
    logger.opt(exception=(exc_type, exc, tb)).critical("未捕获的异常")


def _install_qt_handler() -> None:
    """把 Qt 自己的 qWarning / qCritical 也写进日志。"""
    try:
        from PySide6 import QtCore
    except Exception:  # noqa: BLE001
        return

    level_map = {
        QtCore.QtMsgType.QtDebugMsg: "DEBUG",
        QtCore.QtMsgType.QtInfoMsg: "INFO",
        QtCore.QtMsgType.QtWarningMsg: "WARNING",
        QtCore.QtMsgType.QtCriticalMsg: "ERROR",
        QtCore.QtMsgType.QtFatalMsg: "CRITICAL",
    }

    def handler(msg_type, _ctx, message) -> None:
        logger.log(level_map.get(msg_type, "INFO"), "[Qt] {}", message)

    QtCore.qInstallMessageHandler(handler)


__all__ = ["logger", "setup_logging", "LOG_DIR", "LOG_FILE"]
