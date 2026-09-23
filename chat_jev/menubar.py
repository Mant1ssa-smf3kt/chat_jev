"""菜单栏常驻图标：一眼看出程序在不在跑、盯着谁、最近一次判成什么。

点开菜单可以暂停 / 继续、重新显示上次结果、退出。必须在主线程创建。
"""

from __future__ import annotations

from typing import Callable

import objc
from AppKit import (
    NSColor,
    NSFont,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSAttributedString, NSObject, NSTimer

from .judge import ActionPlan, Verdict

SYMBOL = "bubble.left.and.text.bubble.right"


class _MenuTarget(NSObject):
    """NSMenuItem 的 target 必须是 NSObject，所以把回调包一层。"""

    def initWithCallbacks_(self, callbacks):
        self = objc.super(_MenuTarget, self).init()
        if self is None:
            return None
        self._callbacks = callbacks
        return self

    def togglePause_(self, sender):
        self._callbacks["toggle_pause"]()

    def showLast_(self, sender):
        self._callbacks["show_last"]()

    def quit_(self, sender):
        self._callbacks["quit"]()

    def runExtra_(self, sender):
        self._callbacks["extra"][sender.tag()]()


class StatusBar:
    def __init__(self, on_toggle_pause: Callable[[], None] | None, on_show_last: Callable[[], None],
                 on_quit: Callable[[], None], verdict_ttl: float = 20.0,
                 extra: list[tuple[str, Callable[[], None]]] | None = None) -> None:
        self.verdict_ttl = verdict_ttl
        self._timer: NSTimer | None = None

        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.item.button()
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(SYMBOL, "chat-jev")
        if icon is not None:
            icon.setTemplate_(True)
            button.setImage_(icon)
        button.setImagePosition_(2)      # NSImageLeft：图标在左，文字在右
        button.setToolTip_("chat-jev：判别对方的话是不是字面意思")

        self._target = _MenuTarget.alloc().initWithCallbacks_(
            {"toggle_pause": on_toggle_pause, "show_last": on_show_last, "quit": on_quit,
             "extra": [fn for _, fn in extra or []]})

        menu = NSMenu.alloc().init()
        self.status_item = self._add(menu, "启动中…", None, enabled=False)
        self.last_item = self._add(menu, "还没有判别结果", None, enabled=False)
        self.plan_item = self._add(menu, "", None, enabled=False)
        self.plan_item.setHidden_(True)
        menu.addItem_(NSMenuItem.separatorItem())
        self.pause_item = self._add(menu, "暂停自动判别", "togglePause:")
        self.pause_item.setHidden_(on_toggle_pause is None)      # 没开自动判别就没什么可暂停的
        self._add(menu, "再显示一次上次结果", "showLast:")
        if extra:
            menu.addItem_(NSMenuItem.separatorItem())
            for i, (title, _) in enumerate(extra):
                self._add(menu, title, "runExtra:").setTag_(i)
        menu.addItem_(NSMenuItem.separatorItem())
        self._add(menu, "退出 chat-jev", "quit:", key="q")
        self.item.setMenu_(menu)

    # -- 更新 -------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status_item.setTitle_(text)

    def set_paused(self, paused: bool) -> None:
        self.pause_item.setTitle_("继续自动判别" if paused else "暂停自动判别")
        self._set_title("⏸" if paused else "", None)

    def show_verdict(self, v: Verdict, text: str) -> None:
        label = "YES" if v.literal else "NO"
        color = NSColor.systemGreenColor() if v.literal else NSColor.systemRedColor()
        self._set_title(label, color)
        snippet = text.replace("\n", " ")
        if len(snippet) > 24:
            snippet = snippet[:24] + "…"
        detail = f"{label} {v.p_literal * 100:.0f}%"
        if not v.literal:
            detail += f" → {v.intent}"
        self.last_item.setTitle_(f"{detail}   {snippet}")
        self.plan_item.setHidden_(True)
        self._schedule_clear()

    def show_plan(self, plan: ActionPlan) -> None:
        ranked = plan.ranked()[:3]
        self.plan_item.setTitle_("建议：" + "  /  ".join(f"{k} {v * 100:.0f}%" for k, v in ranked))
        self.plan_item.setHidden_(False)

    def show_pending(self) -> None:
        self._set_title("…", None)

    # -- 内部 -------------------------------------------------------------------

    def _add(self, menu, title, action, enabled=True, key=""):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if action:
            item.setTarget_(self._target)
        item.setEnabled_(enabled)
        menu.addItem_(item)
        return item

    def _set_title(self, text: str, color) -> None:
        button = self.item.button()
        if not text:
            button.setAttributedTitle_(NSAttributedString.alloc().initWithString_(""))
            return
        attrs = {"NSFont": NSFont.boldSystemFontOfSize_(12)}
        if color is not None:
            attrs["NSColor"] = color
        button.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(" " + text, attrs))

    def _schedule_clear(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
        if self.verdict_ttl > 0:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                self.verdict_ttl, False, lambda _t: self._set_title("", None))
