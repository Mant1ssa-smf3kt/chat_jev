"""辅助功能来源：直接读微信 / QQ 窗口里的消息列表，不注入、不碰数据库。

每个应用一个 Adapter，负责把当前打开的聊天窗口解析成 [(sender, name, text), ...]。
AXSource 负责轮询、和上一次快照做 diff、只把新出现的消息交出去。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol

from .. import ax
from ..judge import Message, Sender

BUNDLE_IDS = {
    "qq": "com.tencent.qq",
    "wechat": "com.tencent.xinWeChat",
}

NON_TEXT = "[非文本消息]"


@dataclass(frozen=True)
class Row:
    sender: Sender
    name: str       # 发送者显示名（能拿到就填）
    text: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.sender, self.name, self.text)


@dataclass
class Snapshot:
    contact: str            # 当前聊天对象（窗口标题 / 头部名字）
    rows: list[Row]
    is_group: bool = False  # 群聊：对方不止一个人，判别时用不同的背景描述


class Adapter(Protocol):
    bundle_id: str

    def attach(self, app_el: Any, pid: int) -> None: ...
    def read(self) -> Snapshot | None: ...


# ---------------------------------------------------------------------------
# QQ（QQ NT，Electron）：DOM class 把"自己/对方"标得很清楚
# ---------------------------------------------------------------------------

class QQAdapter:
    bundle_id = BUNDLE_IDS["qq"]

    def __init__(self) -> None:
        self._list: Any = None       # 缓存 ml-list 节点，失效再找
        self._app: Any = None

    def attach(self, app_el: Any, pid: int) -> None:
        self._app, self._list = app_el, None
        ax.enable_chromium_accessibility(app_el)

    def _find_list(self, app_el: Any) -> Any:
        if self._list is not None and ax.children(self._list):
            return self._list
        self._list = None
        for win in ax.attr(app_el, "AXWindows") or []:
            node = ax.find_first(win, lambda n: "ml-list" in ax.dom_classes(n))
            if node is not None:
                self._list = node
                break
        return self._list

    def _contact(self, app_el: Any) -> str:
        for win in ax.attr(app_el, "AXWindows") or []:
            node = ax.find_first(win, lambda n: "chat-header__contact-name" in ax.dom_classes(n))
            if node is not None:
                return ax.description(node) or " ".join(ax.texts_under(node))
        return ""

    def read(self) -> Snapshot | None:
        app_el = self._app
        ml = self._find_list(app_el)
        if ml is None:
            return None
        rows: list[Row] = []
        has_username = False        # 群聊里每条消息都带 user-name 节点，私聊没有
        for item in ax.children(ml):
            cont = ax.find_first(item, lambda n: "message-container" in ax.dom_classes(n), 6)
            if cont is None:
                continue                                    # 时间分隔线、系统提示等
            if not has_username and ax.find_first(cont, lambda n: "user-name" in ax.dom_classes(n), 3) is not None:
                has_username = True
            cls = ax.dom_classes(cont)
            inner = ax.find_first(cont, lambda n: "msg-content-container" in ax.dom_classes(n), 8)
            icls = ax.dom_classes(inner) if inner is not None else set()
            is_me = bool(cls & {"message-container--self", "message-container--align-right"}) or "container--self" in icls
            sender: Sender = "me" if is_me else "them"
            avatar = ax.find_first(cont, lambda n: "avatar-span" in ax.dom_classes(n), 3)
            name = ax.description(avatar) if avatar is not None else ""
            body = ax.find_first(cont, lambda n: "message-content" in ax.dom_classes(n), 8)
            text = " ".join(_texts_skipping_quotes(body)).strip() if body is not None else ""
            rows.append(Row(sender, name, text or NON_TEXT))
        them_names = {r.name for r in rows if r.sender == "them" and r.name}
        return Snapshot(contact=self._contact(app_el), rows=rows,
                        is_group=has_username or len(them_names) >= 2)


def _texts_skipping_quotes(node: Any, max_depth: int = 12) -> list[str]:
    """收集消息正文，跳过引用回复里被引用的那段（class 含 quote 的子树）。"""
    out: list[str] = []
    stack = [(node, 0)]
    while stack:
        n, d = stack.pop()
        if any("quote" in c for c in ax.dom_classes(n)):
            continue
        if ax.role(n) == "AXStaticText":
            t = ax.value(n)
            if t:
                out.append(t)
        if d < max_depth:
            stack.extend((k, d + 1) for k in reversed(ax.children(n)))
    return out


# ---------------------------------------------------------------------------
# 通用兜底：不认识的应用，靠辅助功能树 + 气泡左右位置猜
# ---------------------------------------------------------------------------

class GenericAdapter:
    """不认识的应用：找文本最多的滚动区，靠气泡左右位置分自己/对方。"""

    def __init__(self, bundle_id: str) -> None:
        self.bundle_id = bundle_id
        self._app: Any = None

    def attach(self, app_el: Any, pid: int) -> None:
        self._app = app_el
        ax.enable_chromium_accessibility(app_el)

    def read(self) -> Snapshot | None:
        app_el = self._app
        win = ax.attr(app_el, "AXFocusedWindow") or next(iter(ax.attr(app_el, "AXWindows") or []), None)
        if win is None:
            return None
        best, best_n = None, 0
        for node, _ in ax.walk(win, 30):
            if ax.role(node) in ("AXScrollArea", "AXTable", "AXList", "AXOutline"):
                n = len(ax.texts_under(node, 12))
                if n > best_n:
                    best, best_n = node, n
        if best is None:
            return None
        pos, sz = ax.position(best), ax.size(best)
        mid = pos[0] + sz[0] / 2 if pos and sz else None
        rows: list[Row] = []
        for node, _ in ax.walk(best, 14):
            if ax.role(node) != "AXStaticText":
                continue
            text = ax.value(node).strip()
            if not text:
                continue
            p, s = ax.position(node), ax.size(node)
            center = p[0] + s[0] / 2 if p and s else None
            sender: Sender = "me" if (mid is not None and center is not None and center > mid) else "them"
            rows.append(Row(sender, "", text))
        return Snapshot(contact=ax.attr(win, "AXTitle", "") or "", rows=rows)


def make_adapter(app: str) -> Adapter:
    if app == "qq":
        return QQAdapter()
    if app == "wechat":
        # 微信 4.x 自绘 UI，辅助功能树是空的，只能截图 OCR
        from .ocr import OCRAdapter, WECHAT_LAYOUT
        return OCRAdapter(BUNDLE_IDS["wechat"], WECHAT_LAYOUT)
    return GenericAdapter(app)     # 允许直接传 bundle id


# ---------------------------------------------------------------------------
# 轮询 + diff
# ---------------------------------------------------------------------------

class AppSource:
    """盯着一个应用的聊天窗口，poll() 只吐新消息。读取方式由 adapter 决定（AX 或 OCR）。"""

    name = "app"

    def __init__(
        self,
        app: str,
        contact: str | None = None,       # 只关心这个聊天对象；None = 当前打开的任何聊天
        only_when_frontmost: bool = False, # 只在该应用在前台时读取
        retry_interval: float = 3.0,
    ) -> None:
        self.app = app
        self.adapter = make_adapter(app)
        self.contact = contact
        self.only_when_frontmost = only_when_frontmost
        self._retry_interval = retry_interval
        self._app_el: Any = None
        self._pid: int | None = None
        self._next_attach = 0.0
        self._prev: Snapshot | None = None
        self.last_contact = ""            # 最近一次 poll 看到的聊天对象，供上层区分上下文
        self.last_is_group = False        # 最近一次 poll 看到的是不是群聊

    # -- 应用连接 --------------------------------------------------------------

    def _attach(self) -> bool:
        now = time.monotonic()
        running = ax.running_app(self.adapter.bundle_id)
        if running is None:
            self._app_el, self._pid, self._prev = None, None, None
            return False
        pid = running.processIdentifier()
        if self._app_el is None or pid != self._pid:
            if now < self._next_attach:
                return False
            self._next_attach = now + self._retry_interval
            self._app_el, self._pid, self._prev = ax.app_element(pid), pid, None
            self.adapter.attach(self._app_el, pid)
        return True

    # -- 对外接口 ----------------------------------------------------------------

    def current(self) -> Snapshot | None:
        """读一次当前快照（调试用）。"""
        if not self._attach():
            return None
        return self.adapter.read()

    def poll(self) -> list[Message]:
        if not self._attach():
            return []
        if self.only_when_frontmost and ax.frontmost_bundle_id() != self.adapter.bundle_id:
            return []
        snap = self.adapter.read()
        if snap is None:
            return []
        if self.contact and snap.contact and self.contact not in snap.contact:
            self._prev = None          # 不是要看的聊天，清掉锚点
            return []

        new_rows = self._diff(snap)
        self._prev = snap
        self.last_contact = snap.contact
        self.last_is_group = snap.is_group
        return [Message(r.sender, r.text, r.name) for r in new_rows if r.text != NON_TEXT]

    # -- diff：找上次快照的尾部在这次快照里的位置，后面的就是新消息 -----------------

    def _diff(self, snap: Snapshot) -> list[Row]:
        prev = self._prev
        if prev is None or prev.contact != snap.contact or not prev.rows:
            return []                  # 首次 / 切换了聊天：只建立基线，不回放历史
        if not snap.rows:
            return []
        cur_keys = [r.key for r in snap.rows]
        # 用上次的最后两条做锚点（比一条更能对付重复消息），退化到一条
        for n in (2, 1):
            anchor = [r.key for r in prev.rows[-n:]]
            if len(anchor) < n:
                continue
            idx = _rfind_subseq(cur_keys, anchor)
            if idx is not None:
                return snap.rows[idx + n:]
        # OCR 逐帧结果可能有个别字不同：用上一条做模糊锚点
        last = prev.rows[-1]
        for i in range(len(snap.rows) - 1, -1, -1):
            r = snap.rows[i]
            if r.sender == last.sender and _similar(r.text, last.text):
                return snap.rows[i + 1:]
        # 找不到锚点：列表被大幅滚动或刷新了。保守起见只当作新基线。
        return []


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _rfind_subseq(seq: list, sub: list) -> int | None:
    n = len(sub)
    for i in range(len(seq) - n, -1, -1):
        if seq[i:i + n] == sub:
            return i
    return None

