"""窗口截图 + 系统 Vision OCR。全部离线，不上传任何图片。

截图优先走 ScreenCaptureKit（macOS 14+，不会被系统反复提醒），
不可用时退回 CGWindowListCreateImage。两者都需要「屏幕录制」权限。
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any

import Quartz
from Quartz import (
    CGDataProviderCopyData,
    CGImageGetDataProvider,
    CGImageGetHeight,
    CGImageGetWidth,
    CGPreflightScreenCaptureAccess,
    CGRequestScreenCaptureAccess,
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)
from Vision import VNImageRequestHandler, VNRecognizeTextRequest, VNRequestTextRecognitionLevelAccurate

try:  # ScreenCaptureKit 可能没装绑定；退回 CG
    import ScreenCaptureKit as SCK
except ImportError:  # pragma: no cover
    SCK = None


@dataclass(frozen=True)
class WindowInfo:
    number: int
    x: float
    y: float
    width: float
    height: float
    title: str


@dataclass(frozen=True)
class TextBox:
    """OCR 出的一行文字，坐标是窗口内的点（pt），原点左上。"""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def ensure_screen_access(prompt: bool = True) -> bool:
    if CGPreflightScreenCaptureAccess():
        return True
    if prompt:
        CGRequestScreenCaptureAccess()
    return False


def find_window(pid: int) -> WindowInfo | None:
    """该进程最大的普通层级窗口。"""
    best = None
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []:
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer", 0) != 0:
            continue
        b = w["kCGWindowBounds"]
        info = WindowInfo(int(w["kCGWindowNumber"]), b["X"], b["Y"], b["Width"], b["Height"], w.get("kCGWindowName") or "")
        if info.width < 200 or info.height < 200:
            continue
        if best is None or info.width * info.height > best.width * best.height:
            best = info
    return best


# ---- 截图 ------------------------------------------------------------------

class _SCKCapture:
    """ScreenCaptureKit 截图。SCWindow 对象按 window number 缓存。"""

    def __init__(self) -> None:
        self._windows: dict[int, Any] = {}

    def _refresh(self) -> None:
        done = threading.Event()
        result: dict[str, Any] = {}

        def cb(content, error):
            result["content"], result["error"] = content, error
            done.set()

        SCK.SCShareableContent.getShareableContentWithCompletionHandler_(cb)
        done.wait(10)
        content = result.get("content")
        if content is None:
            return
        self._windows = {int(w.windowID()): w for w in content.windows()}

    def capture(self, info: WindowInfo, scale: float) -> Any | None:
        win = self._windows.get(info.number)
        if win is None:
            self._refresh()
            win = self._windows.get(info.number)
            if win is None:
                return None
        flt = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(win)
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(int(info.width * scale))
        cfg.setHeight_(int(info.height * scale))
        cfg.setShowsCursor_(False)
        cfg.setIgnoreShadowsSingleWindow_(True)

        done = threading.Event()
        result: dict[str, Any] = {}

        def cb(image, error):
            result["image"], result["error"] = image, error
            done.set()

        SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(flt, cfg, cb)
        done.wait(10)
        img = result.get("image")
        if img is None:
            self._windows.pop(info.number, None)   # 窗口可能已换，下次刷新
        return img


class _CGCapture:
    def capture(self, info: WindowInfo, scale: float) -> Any | None:
        return Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, info.number,
            Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageBestResolution)


class WindowCapturer:
    def __init__(self, backend: str = "auto") -> None:
        use_sck = SCK is not None and backend in ("auto", "sck") and hasattr(SCK, "SCScreenshotManager")
        self._impl = _SCKCapture() if use_sck else _CGCapture()
        self.backend = "sck" if use_sck else "cg"
        self._last_digest: str | None = None

    def capture(self, info: WindowInfo, scale: float = 2.0) -> tuple[Any | None, bool]:
        """返回 (CGImage, changed)。图像和上次完全一样时 changed=False，可跳过 OCR。"""
        img = self._impl.capture(info, scale)
        if img is None:
            return None, False
        data = CGDataProviderCopyData(CGImageGetDataProvider(img))
        digest = hashlib.blake2b(bytes(data), digest_size=16).hexdigest() if data is not None else None
        changed = digest != self._last_digest
        self._last_digest = digest
        return img, changed


# ---- OCR --------------------------------------------------------------------

def recognize(img: Any, window: WindowInfo, languages: tuple[str, ...] = ("zh-Hans", "en-US")) -> list[TextBox]:
    """对整张窗口截图做 OCR，把归一化坐标换成窗口内的 pt 坐标（原点左上）。"""
    req = VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(list(languages))
    req.setUsesLanguageCorrection_(True)
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"OCR 失败: {err}")

    W, H = window.width, window.height
    boxes: list[TextBox] = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        text = cands[0].string().strip()
        if not text:
            continue
        bb = obs.boundingBox()    # 归一化，原点左下
        x0 = bb.origin.x * W
        x1 = (bb.origin.x + bb.size.width) * W
        y1 = (1 - bb.origin.y) * H
        y0 = (1 - bb.origin.y - bb.size.height) * H
        boxes.append(TextBox(text, x0, y0, x1, y1))
    boxes.sort(key=lambda b: (b.y0, b.x0))
    return boxes


def image_size(img: Any) -> tuple[int, int]:
    return CGImageGetWidth(img), CGImageGetHeight(img)


def save_png(img: Any, path: str) -> None:
    import AppKit
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(img)
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
    data.writeToFile_atomically_(path, True)
