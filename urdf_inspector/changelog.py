"""版本历史 + GitHub Releases 更新检查。

发新版本时在 RELEASES 最前面加一条，同时改 pyproject.toml / __version__。
"""

from __future__ import annotations

import json
import queue
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import __version__ as APP_VERSION
from .log import logger

REPO_HOME = "https://github.com/ccbs-tools/urdf-inspector"
# 视频教程占位：有正式地址后改这里即可
VIDEO_TUTORIAL = "https://github.com/ccbs-tools/urdf-inspector#demo"
# 方式一：网页 /releases/latest 会 302 到 /releases/tag/<tag>，没有 API 的 60 次/小时限额
RELEASES_LATEST_PAGE = f"{REPO_HOME}/releases/latest"
# 方式二：REST API（未登录按 IP 限 60 次/小时，走共享代理时容易 403）
RELEASES_API = "https://api.github.com/repos/ccbs-tools/urdf-inspector/releases/latest"
# 与 .github/workflows/build.yml 里 "Package zip" 的命名保持一致
ASSET_NAME_FMT = "urdf-inspector-v{ver}-windows-x64.zip"
# 检查更新总预算：两种方式并发竞速，谁先成功用谁；与对话框倒计时一致
UPDATE_CHECK_TIMEOUT_S = 20.0

RELEASES: tuple[dict, ...] = (
    {
        "version": "0.1.0",
        "date": "2026-11-05",
        "notes": {
            "zh": [
                "初始版本。",
                "拖入 URDF 查看（MuJoCo 离屏渲染），点选连杆几何高亮并预览 STL。",
                "关节滑条控制；开关碰撞体 / 坐标系 / 质心 / 物理步进。",
                "支持 URDF <mimic> 从动关节；菜单栏中英文切换。",
                "帮助菜单：仓库主页、版本介绍、检查更新；GitHub Actions 自动打包发布。",
            ],
            "en": [
                "Initial release.",
                "Drop a URDF to inspect it (MuJoCo off-screen); pick link geometry to highlight and preview STL.",
                "Joint sliders; toggle collision / frames / CoM / physics stepping.",
                "URDF <mimic> joints are followed; menu language switch (EN/ZH).",
                "Help menu: repo home, version info, check for updates; GitHub Actions packaging & releases.",
            ],
        },
    },
)


def release_notes(entry: dict, lang: str) -> list[str]:
    notes = entry.get("notes") or {}
    return list(notes.get(lang) or notes.get("en") or [])


def parse_version_tuple(s: str) -> Optional[tuple[int, ...]]:
    s = (s or "").strip().lstrip("vV")
    if not s:
        return None
    parts: list[int] = []
    for p in s.split("."):
        digits = ""
        for ch in p:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def cmp_version(a: str, b: str) -> Optional[int]:
    """a>b → 1，相等 → 0，a<b → -1；无法解析 → None。"""
    ta, tb = parse_version_tuple(a), parse_version_tuple(b)
    if ta is None or tb is None:
        return None
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    if ta > tb:
        return 1
    if ta < tb:
        return -1
    return 0


_UA = {"User-Agent": f"urdf-inspector/{APP_VERSION}"}


def _latest_via_page(timeout_s: float) -> tuple[str, Optional[str]]:
    """HEAD 网页 /releases/latest，跟随 302 后从最终地址取 tag。不占 API 配额。"""
    logger.debug("[page] HEAD {}", RELEASES_LATEST_PAGE)
    req = urllib.request.Request(RELEASES_LATEST_PAGE, method="HEAD", headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        final_url = resp.geturl()
        status = resp.status
    logger.debug("[page] status={} final_url={}", status, final_url)
    m = re.search(r"/releases/tag/([^/?#]+)", final_url)
    if not m:
        raise RuntimeError(f"unexpected redirect: {final_url}")
    tag = urllib.parse.unquote(m.group(1))
    ver = tag.lstrip("vV")
    url = f"{REPO_HOME}/releases/download/{tag}/{ASSET_NAME_FMT.format(ver=ver)}"
    return ver, url


def _latest_via_api(timeout_s: float) -> tuple[str, Optional[str]]:
    """REST API：能拿到真实资源列表，但未登录有 60 次/小时限额。"""
    logger.debug("[api] GET {}", RELEASES_API)
    req = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", **_UA},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        data = json.loads(resp.read().decode("utf-8"))
    logger.debug("[api] status ok, rate-limit remaining={}, assets={}",
                 remaining, [a.get("name") for a in data.get("assets") or []])
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("empty tag_name")
    ver = tag.lstrip("vV")
    url: Optional[str] = None
    assets = data.get("assets") or []
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".zip") and "windows" in name:
            url = asset.get("browser_download_url")
            break
    if url is None:
        for asset in assets:
            if str(asset.get("name") or "").lower().endswith(".zip"):
                url = asset.get("browser_download_url")
                break
    return ver, url


class UpdateCheckError(RuntimeError):
    """所有方式都失败。details: {方式名: 简短原因}，供界面分行显示。"""

    def __init__(self, details: dict[str, str]) -> None:
        super().__init__("; ".join(f"{n}: {r}" for n, r in details.items()))
        self.details = details


def describe_error(exc: BaseException) -> str:
    """把网络异常压成一行短原因（给界面看；完整 repr 走日志）。"""
    e: BaseException = exc
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException):
        e = e.reason
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, ssl.SSLError):
        return f"SSL {e.__class__.__name__}"
    if isinstance(e, OSError) and getattr(e, "strerror", None):
        return f"{e.__class__.__name__}: {e.strerror}"
    text = str(e) or e.__class__.__name__
    return text if len(text) <= 60 else text[:57] + "..."


_METHODS: tuple[tuple[str, Callable[[float], tuple[str, Optional[str]]]], ...] = (
    ("网页跳转", _latest_via_page),
    ("API", _latest_via_api),
)

_check_seq = 0
_check_seq_lock = threading.Lock()


def check_latest_release(timeout_s: float = UPDATE_CHECK_TIMEOUT_S) -> tuple[str, Optional[str]]:
    """查询 GitHub Releases 最新版。返回 (version, windows_zip_url)。

    两种方式**并发竞速**，谁先成功就用谁的结果；全部失败才抛异常（带各自原因）。
    timeout_s 是总预算，与对话框倒计时一致：到点还没有任何成功就抛 TimeoutError，
    迟到的结果只记日志不再使用。在后台线程里跑，可以阻塞。
    """
    global _check_seq
    with _check_seq_lock:
        _check_seq += 1
        seq = _check_seq
    tag = f"#{seq}"

    logger.info("{} 检查更新开始 | 当前 v{} | 预算 {:.0f}s | 并发方式: {}",
                tag, APP_VERSION, timeout_s, " / ".join(n for n, _ in _METHODS))
    t0 = time.perf_counter()
    results: "queue.Queue[tuple[str, bool, object, float]]" = queue.Queue()

    def run(name: str, fn: Callable[[float], tuple[str, Optional[str]]]) -> None:
        t = time.perf_counter()
        try:
            payload = fn(timeout_s)
            dt = (time.perf_counter() - t) * 1000
            logger.debug("{} [{}] 完成 ok 耗时 {:.0f} ms -> {}", tag, name, dt, payload)
            results.put((name, True, payload, dt))
        except Exception as exc:  # noqa: BLE001
            dt = (time.perf_counter() - t) * 1000
            logger.debug("{} [{}] 完成 fail 耗时 {:.0f} ms -> {!r}", tag, name, dt, exc)
            results.put((name, False, exc, dt))

    for name, fn in _METHODS:
        threading.Thread(target=run, args=(name, fn), name=f"update-check-{name}", daemon=True).start()

    deadline = time.monotonic() + timeout_s
    errors: dict[str, BaseException] = {}
    while len(errors) < len(_METHODS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            name, ok, payload, dt = results.get(timeout=remaining)
        except queue.Empty:
            break
        if ok:
            ver, url = payload  # type: ignore[misc]
            logger.info("{} 检查更新成功 [胜出方式={}] 最新 v{} | 下载 {} | 该方式耗时 {:.0f} ms | 总耗时 {:.0f} ms{}",
                        tag, name, ver, url, dt, (time.perf_counter() - t0) * 1000,
                        f" | 已失败: {list(errors)}" if errors else "")
            return ver, url
        errors[name] = payload  # type: ignore[assignment]
        logger.warning("{} [{}] 失败 ({:.0f} ms): {!r}，等待其它方式", tag, name, dt, payload)

    total_ms = (time.perf_counter() - t0) * 1000
    if len(errors) < len(_METHODS):
        pending = [n for n, _ in _METHODS if n not in errors]
        logger.error("{} 预算 {:.0f}s 用尽，仍无成功结果 | 已失败 {} | 仍在等待 {} | 总耗时 {:.0f} ms",
                     tag, timeout_s, list(errors), pending, total_ms)
        raise TimeoutError(f"{timeout_s:.0f}s 内没有任何方式返回成功")
    logger.error("{} 两种方式均失败 | {} | 总耗时 {:.0f} ms", tag,
                 "; ".join(f"{n}: {e!r}" for n, e in errors.items()), total_ms)
    raise UpdateCheckError({n: describe_error(e) for n, e in errors.items()})


__all__ = [
    "APP_VERSION",
    "REPO_HOME",
    "VIDEO_TUTORIAL",
    "UPDATE_CHECK_TIMEOUT_S",
    "RELEASES",
    "release_notes",
    "cmp_version",
    "check_latest_release",
    "UpdateCheckError",
    "describe_error",
]
