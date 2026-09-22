"""屏幕角落的悬浮判别结果：YES（绿）/ NO（红）+ 概率 + 真实意图 + 消息片段。

始终置顶、不抢焦点、可拖动、几秒后自动隐藏。必须在主线程调用。
"""

from __future__ import annotations

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
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
from Foundation import NSTimer

from .judge import ActionPlan, Verdict

W, H, MARGIN = 320, 140, 20

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


class Overlay:
    def __init__(self, hide_after: float = 8.0) -> None:
        self.hide_after = hide_after
        self._timer: NSTimer | None = None

        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - W - MARGIN
        y = screen.origin.y + screen.size.height - H - MARGIN
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
        self.prob = _label(NSMakeRect(130, H - 44, W - 146, 24), 14, alpha=0.95)
        self.intent = _label(NSMakeRect(16, H - 74, W - 32, 20), 13, alpha=0.9)
        self.plan = _label(NSMakeRect(16, H - 96, W - 32, 20), 13, bold=True)
        self.snippet = _label(NSMakeRect(16, 10, W - 32, 30), 12, alpha=0.75)
        for v in (self.verdict, self.prob, self.intent, self.plan, self.snippet):
            self.bg.addSubview_(v)

    # -- public ------------------------------------------------------------------

    def show_pending(self, text: str) -> None:
        self._paint(GREY, "…", "判别中", "", text)

    def show_verdict(self, v: Verdict, text: str) -> None:
        pct = f"{v.p_literal * 100:.0f}%"
        if v.literal:
            self._paint(GREEN, "YES", f"表里一致 {pct}", f"意图：{v.intent}", text)
        else:
            top = v.intent_probs.get(v.intent)
            hint = f"→ {v.intent}" + (f" {top * 100:.0f}%" if top is not None else "")
            self._paint(RED, "NO", f"表里一致仅 {pct}", hint, text)

    def show_error(self, msg: str, text: str = "") -> None:
        self._paint(GREY, "!", "出错", msg, text)

    def show_info(self, title: str, detail: str = "") -> None:
        self._paint(GREY, "✓", title, detail, "")

    def show_plan(self, plan: ActionPlan) -> None:
        """在已显示的判别结果下面补一行建议，不重置颜色；顺便把自动隐藏往后推。"""
        self.plan.setStringValue_(f"建议：{plan.best} {plan.probs.get(plan.best, 0) * 100:.0f}%")
        self.panel.orderFrontRegardless()
        self._schedule_hide()

    def hide(self) -> None:
        self.panel.orderOut_(None)

    # -- internal ----------------------------------------------------------------

    def _paint(self, color, verdict: str, prob: str, intent: str, text: str) -> None:
        self.bg.layer().setBackgroundColor_(color.CGColor())
        self.verdict.setStringValue_(verdict)
        self.prob.setStringValue_(prob)
        self.intent.setStringValue_(intent)
        self.plan.setStringValue_("")
        self.snippet.setStringValue_(text.replace("\n", " "))
        self.panel.orderFrontRegardless()
        self._schedule_hide()

    def _schedule_hide(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
        if self.hide_after > 0:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                self.hide_after, False, lambda _t: self.hide())
