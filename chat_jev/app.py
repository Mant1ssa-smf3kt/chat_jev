"""主循环：轮询消息来源 → 对方的新消息交给 Jev → 终端 / 浮窗输出。

另一个入口是 pick()：用户 ⌥+点击某条消息（哪怕是早就错过、翻回去的），
用它前面的消息做上下文判别，结果贴在气泡旁边。
"""

from __future__ import annotations

import sys
import threading
from collections import defaultdict, deque

from .config import Settings
from .jev import JevClient, JevError
from .judge import ActionPlan, Message, Verdict, judge, rank_actions
from .sources import AppSource, ClipboardSource, Source


def format_verdict(v: Verdict, text: str, name: str = "") -> str:
    if name:
        text = f"{name}: {text}"
    pct = f"{v.p_literal * 100:.0f}%"
    head = f"{'YES' if v.literal else 'NO ':<3} 表里一致 {pct:>4}"
    if not v.literal or v.intent != "字面意思":
        top = v.intent_probs.get(v.intent)
        head += f"  → {v.intent}" + (f" {top * 100:.0f}%" if top is not None else "")
    return f"{head}  |  {text}"


def format_plan(plan: ActionPlan) -> str:
    ranked = plan.ranked()
    top = f"    → 建议：{plan.best} {plan.probs.get(plan.best, 0) * 100:.0f}%  ({plan.descs.get(plan.best, '')})"
    rest = "，".join(f"{k} {v * 100:.0f}%" for k, v in ranked if k != plan.best)
    return top + (f"\n      其他：{rest}" if rest else "")


class Watcher:
    def __init__(self, settings: Settings, source: Source, client: JevClient, overlay=None,
                 history_seed: list[Message] | None = None, out=sys.stdout, sync: bool = False,
                 llm=None, auto: bool = True) -> None:
        self.settings = settings
        self.source = source
        self.client = client
        self.llm = llm              # llm.LLMClient；None = 不生成"下一步建议"
        self.overlay = overlay
        self.out = out
        self.sync = sync            # True = 在当前线程直接请求 Jev（测试用）
        self.auto = auto            # False = 不自动判新消息，只判 ⌥+点击选中的
        self.paused = False         # 暂停时照常记上下文，只是不请求 Jev
        self._seq = 0               # 每次判别 +1；结果回来时不是最新的一次，就不覆盖浮窗
        self._cache: dict[tuple, tuple[Verdict, ActionPlan | None]] = {}   # 同一条消息再点一次直接出结果
        self.last: tuple[Verdict, str, ActionPlan | None] | None = None
        self.statusbar = None       # 菜单栏，GUI 模式下由 run_gui 挂上
        # 按聊天对象分别记上下文；剪贴板来源只有一条
        self.history: dict[str, deque[Message]] = defaultdict(lambda: deque(maxlen=max(settings.history_size * 2, 20)))
        self._seed = list(history_seed or [])   # 启动时窗口里已有的消息，首次轮询时挂到对应聊天下

    def _key(self) -> str:
        return getattr(self.source, "last_contact", "")

    def _is_group(self) -> bool:
        return bool(getattr(self.source, "last_is_group", False))

    def tick(self) -> None:
        """轮询一次。AX 读取很快，直接在调用线程做；Jev 请求丢到后台线程。"""
        try:
            new = self.source.poll()
        except Exception as e:  # AX 偶发失败（窗口切换、进程重启）不应打断循环
            print(f"[source] {e}", file=sys.stderr)
            return
        if not new:
            return
        key = self._key()
        if key not in self.history and self._seed:
            self.history[key].extend(self._seed)
            self._seed = []
        hist = self.history[key]
        group = self._is_group()
        for m in new:
            if m.sender == "them" and self.auto and not self.paused:
                self._judge_async(list(hist), m, group)
            hist.append(m)
        self._refresh_status()

    def pick(self, x: float, y: float) -> bool:
        """⌥+点击：(x, y) 落在某条消息上就判别它，上下文取窗口里它前面的消息。不是消息返回 False。"""
        hit = self.source.pick(x, y) if hasattr(self.source, "pick") else None
        if hit is None:
            return False
        from .sources.ax import NON_TEXT
        snap, i = hit
        row = snap.rows[i]
        if row.text == NON_TEXT:
            self._show(lambda o: o.show_info("这条不是文字消息", "图片 / 表情 / 文件判不了", row.frame))
            return True
        if row.sender == "me":
            self._show(lambda o: o.show_info("这条是你自己发的", "点对方的消息试试", row.frame))
            return True
        history = [Message(r.sender, r.text, r.name) for r in snap.rows[:i] if r.text != NON_TEXT]
        target = Message(row.sender, row.text, row.name)
        self._judge_async(history, target, snap.is_group, anchor=row.frame, contact=snap.contact)
        return True

    def _show(self, fn) -> None:
        if self.overlay is not None:
            fn(self.overlay)

    def status_text(self) -> str:
        who = getattr(self.source, "app", self.source.name)
        contact = self._key()
        state = "已暂停" if self.paused else ("监听中" if self.auto else "点选模式")
        kind = "群" if self._is_group() else "私聊"
        return f"{state} · {who}" + (f" · {kind} · {contact}" if contact else " · 等待打开聊天")

    def _refresh_status(self) -> None:
        if self.statusbar is not None:
            self.statusbar.set_status(self.status_text())

    def _judge_async(self, history: list[Message], target: Message, group: bool = False,
                     anchor=None, contact: str | None = None) -> None:
        self._seq += 1
        seq = self._seq
        key = _cache_key(self._key() if contact is None else contact, history, target)
        shown = f"{target.name}: {target.text}" if target.name else target.text
        cached = self._cache.get(key)
        if cached is not None:              # 点过的消息：直接显示，不再请求
            v, plan = cached
            self.last = (v, shown, plan)
            self._show(lambda o: (o.show_verdict(v, shown, anchor), plan and o.show_plan(plan)))
            if self.statusbar is not None:
                self.statusbar.show_verdict(v, shown)
                if plan is not None:
                    self.statusbar.show_plan(plan)
            return
        self._show(lambda o: o.show_pending(target.text, anchor))
        if self.statusbar is not None:
            self.statusbar.show_pending()
        args = (history, target, group, anchor, seq, key)
        if self.sync:
            self._judge(*args)
        else:
            threading.Thread(target=self._judge, args=args, daemon=True).start()

    def _latest(self, seq: int) -> bool:
        return seq == self._seq

    def _judge(self, history: list[Message], target: Message, group: bool = False,
               anchor=None, seq: int = 0, key: tuple = ()) -> None:
        try:
            v = judge(self.client, history, target,
                      relation=self.settings.relation, threshold=self.settings.threshold,
                      history_size=self.settings.history_size, group=group)
        except JevError as e:
            print(f"[jev] {e}", file=sys.stderr)
            if self.overlay is not None and self._latest(seq):
                _on_main(lambda: self.overlay.show_error(str(e)[:60], target.text, anchor))
            return
        print(format_verdict(v, target.text, target.name), file=self.out, flush=True)
        shown = f"{target.name}: {target.text}" if target.name else target.text
        self._cache[key] = (v, None)
        if self._latest(seq):
            self.last = (v, shown, None)
            if self.overlay is not None:
                _on_main(lambda: self.overlay.show_verdict(v, shown, anchor))
            if self.statusbar is not None:
                _on_main(lambda: self.statusbar.show_verdict(v, shown))
        if self.llm is not None:
            self._plan(history, target, v, group, shown, seq, key)

    def _plan(self, history: list[Message], target: Message, v: Verdict, group: bool, shown: str,
              seq: int = 0, key: tuple = ()) -> None:
        """第二段：LLM 提候选 → Jev 打分布。失败只打日志，不影响已经出的 yes/no。"""
        from .llm import LLMError, propose_actions
        try:
            cands = propose_actions(self.llm, history, target, v, relation=self.settings.relation, group=group)
            plan = rank_actions(self.client, history, target, v, cands, relation=self.settings.relation,
                                history_size=self.settings.history_size, group=group)
        except (LLMError, JevError) as e:
            print(f"[plan] {e}", file=sys.stderr)
            return
        print(format_plan(plan), file=self.out, flush=True)
        self._cache[key] = (v, plan)
        if not self._latest(seq):
            return
        self.last = (v, shown, plan)
        if self.overlay is not None:
            _on_main(lambda: self.overlay.show_plan(plan))
        if self.statusbar is not None:
            _on_main(lambda: self.statusbar.show_plan(plan))


def _cache_key(contact: str, history: list[Message], target: Message) -> tuple:
    """同一个聊天里、同样的前三条 + 这一条，就当成同一条消息。"""
    return (contact, *((m.sender, m.name, m.text) for m in [*history[-3:], target]))


def _on_main(fn) -> None:
    from PyObjCTools import AppHelper
    AppHelper.callAfter(fn)


def build_source(kind: str, app: str, contact: str | None, frontmost: bool) -> Source:
    if kind == "clipboard":
        return ClipboardSource()
    return AppSource(app, contact=contact, only_when_frontmost=frontmost)


def run_terminal(watcher: Watcher, interval: float) -> None:
    import time
    print(f"[watch] source={watcher.source.name} 每 {interval}s 轮询，Ctrl-C 退出", file=sys.stderr)
    try:
        while True:
            watcher.tick()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def run_gui(watcher: Watcher, interval: float, hide_after: float, pick: bool = True,
            waiting_permission: bool = False) -> None:
    """浮窗 + 菜单栏图标。程序不进 Dock，靠菜单栏图标确认它活着。"""
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from Foundation import NSTimer
    from PyObjCTools import AppHelper

    from .menubar import StatusBar
    from .overlay import Overlay

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # 不出现在 Dock
    watcher.overlay = Overlay(hide_after=hide_after)

    def toggle_pause():
        watcher.paused = not watcher.paused
        watcher.statusbar.set_paused(watcher.paused)
        watcher._refresh_status()

    def show_last():
        if watcher.last is not None:
            v, shown, plan = watcher.last
            watcher.overlay.show_verdict(v, shown)
            if plan is not None:
                watcher.overlay.show_plan(plan)
        else:
            watcher.overlay.show_info("还没有判别结果", watcher.status_text())

    from .config import FROZEN
    extra = []
    if FROZEN:
        from .bundle import open_config, open_log
        extra = [("打开配置文件…", open_config), ("打开日志", open_log)]
    watcher.statusbar = StatusBar(on_toggle_pause=toggle_pause, on_show_last=show_last,
                                  on_quit=AppHelper.stopEventLoop, extra=extra)
    watcher._refresh_status()
    if waiting_permission:
        _wait_for_permission(watcher)
    else:
        watcher.overlay.show_info("chat-jev 已启动", watcher.status_text() + "，结果会显示在这里和菜单栏")

    picker = None
    if pick and hasattr(watcher.source, "pick"):
        from .picker import ClickPicker
        picker = ClickPicker(watcher.pick)      # 局部变量撑到事件循环结束，监听不会被回收
        print("[watch] 按住 ⌥ 点 QQ 里任意一条对方的消息，就在旁边判别它", file=sys.stderr)

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(interval, True, lambda _t: watcher.tick())
    print(f"[watch] source={watcher.source.name} 浮窗模式，每 {interval}s 轮询，菜单栏图标可退出，或 Ctrl-C", file=sys.stderr)
    try:
        AppHelper.runEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        pass


def _wait_for_permission(watcher: Watcher) -> None:
    """没有辅助功能权限时先挂着提示，每 2 秒查一次，打开了就接着干活，不用重启。"""
    from Foundation import NSTimer

    from . import ax
    hint = "系统设置 → 隐私与安全性 → 辅助功能，打开 chat-jev"
    watcher.overlay.hide_after, keep = 0, watcher.overlay.hide_after    # 提示一直挂着
    watcher.overlay.show_info("需要辅助功能权限", hint)
    watcher.statusbar.set_status("等待辅助功能权限 · " + hint)

    def check(timer):
        if not ax.ensure_trusted(prompt=False):
            return
        timer.invalidate()
        watcher.overlay.hide_after = keep
        watcher.overlay.show_info("已获得权限，开始工作", "打开 QQ 的聊天窗口即可")
        watcher._refresh_status()
        print("[watch] 已获得辅助功能权限", file=sys.stderr)

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(2.0, True, check)


run_overlay = run_gui
