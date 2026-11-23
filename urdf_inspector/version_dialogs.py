"""「版本介绍」与「检查更新」对话框。文案键 chg.* / upd.* 在 i18n.py 中。"""

from __future__ import annotations

import math
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .changelog import (
    APP_VERSION,
    RELEASES,
    UPDATE_CHECK_TIMEOUT_S,
    UpdateCheckError,
    check_latest_release,
    cmp_version,
    describe_error,
    release_notes,
)
from .i18n import i18n, tr
from .log import logger

DIALOG_FONT_FAMILY = "Microsoft YaHei UI"
DIALOG_FONT_PT = 10
COUNTDOWN_TICK_MS = 30
PROGRESS_QSS = """
QProgressBar { border: 1px solid #b0bec5; border-radius: 4px; background: #eceff1;
               min-height: 20px; max-height: 20px; text-align: center; color: #263238; }
QProgressBar::chunk { background: #1976d2; border-radius: 3px; }
"""


def dialog_font() -> QFont:
    f = QFont(DIALOG_FONT_FAMILY, DIALOG_FONT_PT)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    return f


def _changelog_html(lang: str) -> str:
    parts = [f"<div style=\"font-family:'{DIALOG_FONT_FAMILY}',sans-serif;font-size:{DIALOG_FONT_PT}pt\">"]
    for e in RELEASES:
        ver = e.get("version", "")
        date = e.get("date", "")
        parts.append(
            f"<p style='margin-bottom:2px'><b>v{ver}</b> &nbsp;"
            f"<span style='color:#888'>{date}</span></p>"
        )
        notes = release_notes(e, lang)
        if notes:
            parts.append("<ul style='margin-top:0'>")
            parts.extend(f"<li>{n}</li>" for n in notes)
            parts.append("</ul>")
    parts.append("</div>")
    return "".join(parts)


_LIVE_WORKERS: set["_CheckWorker"] = set()


class _CheckWorker(QObject):
    """后台查 GitHub Releases。daemon 线程：取消/退出不必等它跑完。

    不挂 parent：对话框关掉后 worker 不会跟着被销毁，线程迟到的结果不会再撞上
    "Signal source has been deleted"。_LIVE_WORKERS 在线程结束前持有引用防止被 GC。
    """

    done = Signal(str, object)   # version, download_url | None
    failed = Signal(object)      # 异常对象，由对话框分类显示

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def start(self) -> None:
        _LIVE_WORKERS.add(self)
        threading.Thread(target=self._run, name=f"{APP_NAME}-update-check", daemon=True).start()

    def _run(self) -> None:
        try:
            try:
                ver, url = check_latest_release(UPDATE_CHECK_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                if self._cancelled:
                    logger.debug("late update-check failure after dialog closed, dropped: {!r}", exc)
                    return
                self._emit(self.failed, exc)
                return
            if self._cancelled:
                logger.debug("late update-check result (v{}) after dialog closed, dropped", ver)
                return
            self._emit(self.done, ver, url)
        finally:
            _LIVE_WORKERS.discard(self)

    @staticmethod
    def _emit(sig, *args) -> None:
        try:
            sig.emit(*args)
        except RuntimeError as exc:  # C++ 对象已销毁
            logger.debug("worker signal emit failed (object deleted): {}", exc)


class UpdateCheckDialog(QDialog):
    """检查更新：倒计时进度条（从满往回退），到 0 算超时。结果显示在同一框里。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("upd.title"))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setFont(dialog_font())
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        self.msg = QLabel(tr("upd.checking"))
        self.msg.setWordWrap(True)
        self._total_ms = max(1, int(round(UPDATE_CHECK_TIMEOUT_S * 1000)))
        self._left_ms = self._total_ms
        self._t0 = time.monotonic()
        self.bar = QProgressBar()
        self.bar.setRange(0, self._total_ms)
        self.bar.setValue(self._total_ms)
        self.bar.setTextVisible(True)
        self.bar.setStyleSheet(PROGRESS_QSS)
        self.bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._show_remaining()

        # 失败详情：默认隐藏，失败时按方式分行显示，可滚动/可选中复制
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        self.details.setFixedHeight(72)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.details.setStyleSheet(
            "QPlainTextEdit { background: #f5f5f5; color: #555; border: 1px solid #ddd; "
            "border-radius: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 9pt; }"
        )

        self.btn_download = QPushButton(tr("upd.download"))
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self._open_download)
        self.btn = QPushButton(tr("upd.cancel"))
        self.btn.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_download)
        row.addWidget(self.btn)
        lay.addWidget(self.msg)
        lay.addWidget(self.bar)
        lay.addWidget(self.details)
        lay.addLayout(row)

        self._finished = False
        self._download_url: str | None = None
        self._worker = _CheckWorker()
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick.setInterval(COUNTDOWN_TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._worker.start()

    def _show_remaining(self) -> None:
        sec = math.ceil(self._left_ms / 1000.0)
        self.bar.setFormat(tr("upd.countdown", sec=sec))

    def _on_tick(self) -> None:
        if self._finished:
            return
        elapsed_ms = int((time.monotonic() - self._t0) * 1000.0)
        self._left_ms = max(0, self._total_ms - elapsed_ms)
        self.bar.setValue(self._left_ms)
        self._show_remaining()
        if self._left_ms <= 0:
            self._on_timeout()

    def _settle(self, text: str, *, download_url: str | None = None,
                details: str | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        self._tick.stop()
        self.bar.setVisible(False)          # 倒计时结束，进度条没用了
        self.msg.setText(text)
        if details:
            self.details.setPlainText(details)
            self.details.setVisible(True)
        self.btn.setText(tr("upd.close"))
        self._download_url = download_url
        self.btn_download.setVisible(bool(download_url))
        self.adjustSize()

    def _open_download(self) -> None:
        if self._download_url:
            ok = QDesktopServices.openUrl(QUrl(self._download_url))
            logger.info("open download url: {} -> {}", self._download_url, "ok" if ok else "failed")

    def _on_done(self, latest: str, url: object) -> None:
        if self._finished:
            logger.debug("update result arrived after dialog settled (timeout/cancel), dropped: v{}", latest)
            return
        download = str(url) if url else None
        c = cmp_version(str(latest), APP_VERSION)
        if c is not None and c > 0:
            logger.info("verdict: new version v{} available (current v{})", latest, APP_VERSION)
            self._settle(
                tr("upd.newer", cur=APP_VERSION, latest=latest),
                download_url=download,
            )
        else:
            logger.info("verdict: up to date (remote v{}, current v{}, cmp={})", latest, APP_VERSION, c)
            self._settle(tr("upd.latest", cur=APP_VERSION))

    def _on_failed(self, exc: object) -> None:
        if self._finished:
            return
        if isinstance(exc, UpdateCheckError):
            logger.warning("verdict: check failed - {}", exc)
            lines = "\n".join(f"{n}: {r}" for n, r in exc.details.items())
            self._settle(tr("upd.failed_short"), details=lines)
        elif isinstance(exc, TimeoutError):
            logger.warning("verdict: background budget exhausted - {}", exc)
            self._settle(tr("upd.timeout", sec=int(UPDATE_CHECK_TIMEOUT_S)))
        else:
            logger.warning("verdict: check failed - {!r}", exc)
            reason = describe_error(exc) if isinstance(exc, BaseException) else str(exc)
            self._settle(tr("upd.failed_short"), details=reason)

    def _on_timeout(self) -> None:
        logger.warning("verdict: {:.0f}s countdown elapsed without result", UPDATE_CHECK_TIMEOUT_S)
        self._worker.cancel()
        self._settle(tr("upd.timeout", sec=int(UPDATE_CHECK_TIMEOUT_S)))

    def reject(self) -> None:
        if not self._finished:
            logger.info("user cancelled update check (waited {:.1f} s)", time.monotonic() - self._t0)
        self._finished = True
        self._worker.cancel()
        self._tick.stop()
        super().reject()


class ChangelogDialog(QDialog):
    """版本介绍：按 RELEASES 列出，底部可直接去检查更新。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("chg.title", ver=APP_VERSION))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setFont(dialog_font())
        self.resize(520, 380)

        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setFont(dialog_font())
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(_changelog_html(i18n.lang))
        lay.addWidget(self.view, 1)

        box = QDialogButtonBox()
        self.btn_check = box.addButton(tr("chg.check"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_close = box.addButton(tr("chg.close"), QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_check.clicked.connect(self._check)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _check(self) -> None:
        UpdateCheckDialog(self).exec()


__all__ = ["ChangelogDialog", "UpdateCheckDialog"]
