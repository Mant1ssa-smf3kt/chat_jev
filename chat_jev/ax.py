"""macOS 辅助功能（Accessibility）API 的薄封装。"""

from __future__ import annotations

from typing import Any, Iterator

from AppKit import NSRunningApplication, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)


def ensure_trusted(prompt: bool = True) -> bool:
    if AXIsProcessTrusted():
        return True
    if prompt:
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
    return False


def running_app(bundle_id: str) -> NSRunningApplication | None:
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == bundle_id:
            return app
    return None


def frontmost_bundle_id() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.bundleIdentifier() if app else None


def app_element(pid: int) -> Any:
    return AXUIElementCreateApplication(pid)


def attr(el: Any, name: str, default: Any = None) -> Any:
    err, val = AXUIElementCopyAttributeValue(el, name, None)
    return val if err == kAXErrorSuccess else default


def set_attr(el: Any, name: str, value: Any) -> bool:
    return AXUIElementSetAttributeValue(el, name, value) == kAXErrorSuccess


def children(el: Any) -> list[Any]:
    return list(attr(el, "AXChildren") or [])


def role(el: Any) -> str:
    return attr(el, "AXRole", "") or ""


def value(el: Any) -> str:
    v = attr(el, "AXValue")
    return v if isinstance(v, str) else ""


def description(el: Any) -> str:
    v = attr(el, "AXDescription")
    return v if isinstance(v, str) else ""


def dom_classes(el: Any) -> set[str]:
    """Chromium/Electron 应用会把 DOM class 暴露成 AXDOMClassList。"""
    v = attr(el, "AXDOMClassList")
    return set(v) if v else set()


def position(el: Any) -> tuple[float, float] | None:
    v = attr(el, "AXPosition")
    if v is None:
        return None
    ok, p = AXValueGetValue(v, kAXValueCGPointType, None)
    return (p.x, p.y) if ok else None


def size(el: Any) -> tuple[float, float] | None:
    v = attr(el, "AXSize")
    if v is None:
        return None
    ok, s = AXValueGetValue(v, kAXValueCGSizeType, None)
    return (s.width, s.height) if ok else None


def walk(el: Any, max_depth: int = 60) -> Iterator[tuple[Any, int]]:
    """深度优先遍历，yield (element, depth)。"""
    stack = [(el, 0)]
    while stack:
        node, depth = stack.pop()
        yield node, depth
        if depth < max_depth:
            kids = children(node)
            stack.extend((k, depth + 1) for k in reversed(kids))


def find_first(el: Any, pred, max_depth: int = 60) -> Any | None:
    for node, _ in walk(el, max_depth):
        if pred(node):
            return node
    return None


def enable_chromium_accessibility(app_el: Any) -> None:
    """Electron/Chromium 默认不暴露网页内容的无障碍树，要主动打开。

    Electron 认 AXManualAccessibility；Chromium 认 AXEnhancedUserInterface。
    两个都设一遍，失败也无妨。
    """
    set_attr(app_el, "AXManualAccessibility", True)
    set_attr(app_el, "AXEnhancedUserInterface", True)


def texts_under(el: Any, max_depth: int = 20) -> list[str]:
    """收集一个节点下所有 AXStaticText 的文本（按遍历顺序）。"""
    out = []
    for node, _ in walk(el, max_depth):
        if role(node) == "AXStaticText":
            t = value(node)
            if t:
                out.append(t)
    return out
