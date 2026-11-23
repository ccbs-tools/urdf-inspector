"""应用图标：优先加载 assets/icon.ico（源码运行取项目根目录，打包后取 _MEIPASS），找不到就现画一个。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from . import APP_NAME


def assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def draw_icon_pixmap(size: int) -> QPixmap:
    """回退图标：蓝底圆角方块 + 应用名首字母。正式图标请放 assets/icon.ico。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1e6fd9"))
    p.drawRoundedRect(QRectF(4 * s, 4 * s, 56 * s, 56 * s), 12 * s, 12 * s)
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", max(6, int(30 * s)), QFont.Weight.Bold)
    p.setFont(font)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, (APP_NAME[:1] or "C").upper())
    p.end()
    return pm


def app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        path = assets_dir() / name
        if path.is_file():
            return QIcon(str(path))
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_icon_pixmap(sz))
    return icon


__all__ = ["app_icon", "assets_dir"]
