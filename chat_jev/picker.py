"""⌥+点击选中消息：全局监听鼠标，按住 Option 点一下，就把点击位置交给回调。

只是旁听，点击照常送到被点的应用，不拦截、不改事件。必须在主线程创建，且需要 NSApplication 事件循环在跑。
"""

from __future__ import annotations

from typing import Callable

from AppKit import (
    NSEvent,
    NSEventMaskLeftMouseDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSScreen,
)

_MODS = NSEventModifierFlagOption | NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagShift


def cocoa_to_ax(x: float, y: float) -> tuple[float, float]:
    """Cocoa 屏幕坐标（原点主屏左下，y 向上）→ 辅助功能坐标（原点主屏左上，y 向下）。"""
    primary_h = NSScreen.screens()[0].frame().size.height
    return x, primary_h - y


class ClickPicker:
    def __init__(self, on_pick: Callable[[float, float], None]) -> None:
        self.on_pick = on_pick
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskLeftMouseDown, self._handle)

    def _handle(self, event) -> None:
        if event.modifierFlags() & _MODS != NSEventModifierFlagOption:   # 只认单独按 ⌥
            return
        loc = NSEvent.mouseLocation()
        self.on_pick(*cocoa_to_ax(loc.x, loc.y))

    def stop(self) -> None:
        if self._monitor is not None:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
