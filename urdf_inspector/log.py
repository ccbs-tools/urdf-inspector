"""日志（loguru）。

文件：%APPDATA%\\ccbs\\urdf-inspector\\logs\\app.log，10 MB 轮转，保留 3 个（含当前）。
用法：
    from .log import logger
    logger.info("...")

日志文本一律英文，不走 i18n。不得记录密码、口令或任何解密后的秘密。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from loguru import logger

from . import APP_NAME, ORG

APP_DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / ORG / APP_NAME
LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"
ROTATION = "10 MB"
RETENTION = 3

_FILE_FMT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | "
    "{name}:{function}:{line} | {message}"
)
_CONSOLE_FMT = (
    "<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
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
        enqueue=True,       # 后台线程也能安全写
        backtrace=False,
        diagnose=False,     # 不 dump 局部变量（可能含秘密）
    )

    sys.excepthook = _excepthook
    _install_stdlib_bridge()
    _install_qt_handler()
    return LOG_FILE


def _excepthook(exc_type, exc, tb) -> None:
    logger.opt(exception=(exc_type, exc, tb)).critical("Unhandled exception")


class _InterceptHandler(logging.Handler):
    """把 stdlib `logging` 的记录（第三方库）转进 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, "[{}] {}", record.name, record.getMessage())


def _install_stdlib_bridge() -> None:
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)
    # 太吵的第三方 logger 在这里单独调级别，例如：
    # logging.getLogger("paramiko").setLevel(logging.INFO)


def _install_qt_handler() -> None:
    """把 Qt 自己的 qWarning / qCritical 写进日志。"""
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


__all__ = ["logger", "setup_logging", "APP_DATA_DIR", "LOG_DIR", "LOG_FILE"]
