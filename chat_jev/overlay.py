"""悬浮判别结果：YES（绿）/ NO（红）+ 概率 + 真实意图 + 消息片段。

新消息的结果显示在屏幕右上角；⌥+点击选中的消息，结果贴在那个气泡旁边（传 anchor）。
始终置顶、不抢焦点、可拖动、几秒后自动隐藏，右上角 × 可随时关掉。必须在主线程调用。
"""

from __future__ import annotations

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject, NSTimer

from .judge import ActionPlan, Verdict

W, H, MARGIN, GAP = 320, 140, 20, 12
PLAN_LINGER = 3.0   # 建议行出来后至少再留几秒

Rect = tuple[float, float, float, float]   # 辅助功能坐标 (x, y, w, h)：原点主屏左上

GREEN = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.13, 0.60, 0.32, 0.96)
RED = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.20, 0.22, 0.96)
GREY = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.25, 0.25, 0.28, 0.96)


def _label(frame, size, bold=False, alpha=1.0):
    f = NSTextField.alloc().initWithFrame_(frame)
    f.setBezeled_(False); f.setDrawsBackground_(False); f.setEditable_(False); f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, alpha))
    f.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail
    return f


class _CloseTarget(NSObject):
    """NSButton 的 target 必须是 ObjC 对象，这里转手调回 Python。"""

    def initWithCallback_(self, cb):
        self = objc.super(_CloseTarget, self).init()
        if self is not None:
            self.cb = cb
        return self

    def close_(self, _sender) -> None:
        self.cb()


class Overlay:
    def __init__(self, hide_after: float = 5.0) -> None:
        self.hide_after = hide_after
        self._timer: NSTimer | None = None
        self._home: tuple[float, float] | None = None   # 贴到气泡旁之前的位置，None = 当前就在常驻位置

        x, y = self._corner()
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H), style, NSBackingStoreBuffered, False)
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setMovableByWindowBackground_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)

        self.bg = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        self.bg.setWantsLayer_(True)
        self.bg.layer().setCornerRadius_(14.0)
        self.panel.setContentView_(self.bg)

        self.verdict = _label(NSMakeRect(16, H - 52, 120, 40), 30, bold=True)
        self.prob = _label(NSMakeRect(130, H - 44, W - 166, 24), 14, alpha=0.95)
        self.intent = _label(NSMakeRect(16, H - 74, W - 32, 20), 13, alpha=0.9)
        self.plan = _label(NSMakeRect(16, H - 96, W - 32, 20), 13, bold=True)
        self.snippet = _label(NSMakeRect(16, 10, W - 32, 30), 12, alpha=0.75)
        for v in (self.verdict, self.prob, self.intent, self.plan, self.snippet):
            self.bg.addSubview_(v)

        self._close_target = _CloseTarget.alloc().initWithCallback_(self.hide)
        close = NSButton.alloc().initWithFrame_(NSMakeRect(W - 32, H - 32, 24, 24))
        close.setBordered_(False)
        close.setTitle_("✕")
        close.setFont_(NSFont.systemFontOfSize_(14))
        close.setContentTintColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.8))
        close.setTarget_(self._close_target)
        close.setAction_("close:")
        close.setToolTip_("关闭")
        self.bg.addSubview_(close)

    # -- public ------------------------------------------------------------------

    def show_pending(self, text: str, anchor: Rect | None = None) -> None:
        self._paint(GREY, "…", "判别中", "", text, anchor)

    def show_verdict(self, v: Verdict, text: str, anchor: Rect | None = None) -> None:
        pct = f"{v.p_literal * 100:.0f}%"
        if v.literal:
            self._paint(GREEN, "YES", f"表里一致 {pct}", f"意图：{v.intent}", text, anchor)
        else:
            top = v.intent_probs.get(v.intent)
            hint = f"→ {v.intent}" + (f" {top * 100:.0f}%" if top is not None else "")
            self._paint(RED, "NO", f"表里一致仅 {pct}", hint, text, anchor)

    def show_error(self, msg: str, text: str = "", anchor: Rect | None = None) -> None:
        self._paint(GREY, "!", "出错", msg, text, anchor)

    def show_info(self, title: str, detail: str = "", anchor: Rect | None = None) -> None:
        self._paint(GREY, "✓", title, detail, "", anchor)

    def show_plan(self, plan: ActionPlan) -> None:
        """在已显示的判别结果下面补一行建议，不重置颜色。

        浮窗已经关掉（自动隐藏或点了 ×）就不再弹出来；还在的话只把自动隐藏推迟一点，
        免得建议刚出来就消失，但不再从头计时。
        """
        self.plan.setStringValue_(f"建议：{plan.best} {plan.probs.get(plan.best, 0) * 100:.0f}%")
        if self.panel.isVisible():
            self._schedule_hide(min(self.hide_after, PLAN_LINGER))

    def hide(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        self.panel.orderOut_(None)

    # -- internal ----------------------------------------------------------------

    def _corner(self) -> tuple[float, float]:
        screen = NSScreen.mainScreen().visibleFrame()
        return (screen.origin.x + screen.size.width - W - MARGIN,
                screen.origin.y + screen.size.height - H - MARGIN)

    def _near(self, anchor: Rect) -> tuple[float, float]:
        """贴在气泡右边、顶部对齐；右边放不下就放左边。结果换算成 Cocoa 坐标并夹在屏幕内。"""
        ax_x, ax_y, aw, ah = anchor
        primary_h = NSScreen.screens()[0].frame().size.height
        top = primary_h - ax_y                      # 气泡顶边的 Cocoa y
        cx, cy = ax_x + aw / 2, top - ah / 2
        vf = next((s.visibleFrame() for s in NSScreen.screens()
                   if s.frame().origin.x <= cx <= s.frame().origin.x + s.frame().size.width
                   and s.frame().origin.y <= cy <= s.frame().origin.y + s.frame().size.height),
                  NSScreen.mainScreen().visibleFrame())
        left, right = vf.origin.x, vf.origin.x + vf.size.width
        bottom, ceil = vf.origin.y, vf.origin.y + vf.size.height
        x = ax_x + aw + GAP
        if x + W > right:
            x = ax_x - W - GAP
        x = min(max(x, left), right - W)
        y = min(max(top - H, bottom), ceil - H)
        return x, y

    def _place(self, anchor: Rect | None) -> None:
        """有 anchor 就挪到气泡旁；没有就回到常驻位置（用户拖过就是拖到的地方）。"""
        if anchor is not None:
            if self._home is None:
                o = self.panel.frame().origin
                self._home = (o.x, o.y)
            self.panel.setFrameOrigin_(NSMakePoint(*self._near(anchor)))
        elif self._home is not None:
            self.panel.setFrameOrigin_(NSMakePoint(*self._home))
            self._home = None

    def _paint(self, color, verdict: str, prob: str, intent: str, text: str, anchor: Rect | None = None) -> None:
        self._place(anchor)
        self.bg.layer().setBackgroundColor_(color.CGColor())
        self.verdict.setStringValue_(verdict)
        self.prob.setStringValue_(prob)
        self.intent.setStringValue_(intent)
        self.plan.setStringValue_("")
        self.snippet.setStringValue_(text.replace("\n", " "))
        self.panel.orderFrontRegardless()
        self._schedule_hide()

    def _schedule_hide(self, after: float | None = None) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        after = self.hide_after if after is None else after
        if after > 0:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                after, False, lambda _t: self.hide())
