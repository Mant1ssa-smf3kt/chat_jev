"""OCR 适配器：截当前聊天窗口，用 Vision 识别文字，按气泡位置分"我 / 对方"。

微信 4.x（Mac）自绘界面，辅助功能拿不到内容，只能走这条路。
布局参数以 pt 为单位、相对窗口左上角，可用环境变量微调（见 README）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from typing import Any

from .. import capture
from ..judge import Sender
from .ax import NON_TEXT, Row, Snapshot


@dataclass(frozen=True)
class Layout:
    chat_left: float     # 聊天区左边界（左边是会话列表）
    header: float        # 顶部标题栏高度（联系人名字在这里）
    footer: float        # 底部输入区高度（用户正在打的字不算消息）
    edge: float          # 气泡贴边判定：离左/右边多少 pt 以内算贴边
    line_gap: float      # 同一气泡内相邻两行的最大间距（相对行高的倍数）

    def with_env(self, prefix: str) -> "Layout":
        kw = {}
        for f in ("chat_left", "header", "footer", "edge", "line_gap"):
            v = os.environ.get(f"{prefix}_{f.upper()}")
            if v:
                kw[f] = float(v)
        return replace(self, **kw) if kw else self


WECHAT_LAYOUT = Layout(chat_left=300, header=60, footer=170, edge=110, line_gap=1.4)

_TIME_RE = re.compile(r"^(\d{1,2}:\d{2}|昨天|Yesterday|星期.|[A-Z][a-z]{2,8}day|\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}月\d{1,2}日)")


class OCRAdapter:
    def __init__(self, bundle_id: str, layout: Layout, env_prefix: str = "JEV_WECHAT") -> None:
        self.bundle_id = bundle_id
        self.layout = layout.with_env(env_prefix)
        self._pid: int | None = None
        self._cap = capture.WindowCapturer()
        self._last: Snapshot | None = None
        self.last_boxes: list[capture.TextBox] = []   # 调试 / 校准用
        self._last_img: Any = None

    def attach(self, app_el: Any, pid: int) -> None:
        self._pid = pid
        self._last = None

    # -- 主流程 -------------------------------------------------------------------

    def read(self) -> Snapshot | None:
        if self._pid is None:
            return None
        win = capture.find_window(self._pid)
        if win is None:
            return None
        img, changed = self._cap.capture(win)
        if img is None:
            return None
        if not changed and self._last is not None:
            return self._last                      # 画面没变，省一次 OCR
        boxes = capture.recognize(img, win)
        snap = self.parse(boxes, win.width, win.height)
        self._last, self.last_boxes, self._last_img = snap, boxes, img
        return snap

    def save_last_image(self, path: str) -> None:
        if self._last_img is not None:
            capture.save_png(self._last_img, path)

    def parse(self, boxes: list[capture.TextBox], width: float, height: float) -> Snapshot:
        L = self.layout
        right = width
        contact = ""
        lines: list[capture.TextBox] = []
        for b in boxes:
            if b.x1 <= L.chat_left:
                continue                             # 会话列表
            if b.y1 <= L.header:
                if not contact and b.x0 < L.chat_left + 200:
                    contact = b.text                 # 标题栏最靠左的文字是联系人名
                continue
            if b.y0 >= height - L.footer:
                continue                             # 输入区
            lines.append(b)

        rows: list[Row] = []
        bubble: list[capture.TextBox] = []
        bubble_side: Sender | None = None

        def flush() -> None:
            if bubble and bubble_side:
                text = " ".join(x.text for x in bubble).strip()
                rows.append(Row(bubble_side, "", text or NON_TEXT))
            bubble.clear()

        for b in lines:
            side = self._side(b, L.chat_left, right)
            if side is None:                          # 居中：时间戳 / 系统消息
                flush(); bubble_side = None
                continue
            same = (bubble and side == bubble_side
                    and b.y0 - bubble[-1].y1 <= L.line_gap * max(b.h, bubble[-1].h)
                    and abs(b.x0 - bubble[0].x0) <= 12)   # 同一气泡内文字左对齐
            if not same:
                flush()
                bubble_side = side
            bubble.append(b)
        flush()
        return Snapshot(contact=contact, rows=rows)

    def _side(self, b: capture.TextBox, left: float, right: float) -> Sender | None:
        if _TIME_RE.match(b.text) and b.h < 13:
            return None
        if right - b.x1 <= self.layout.edge and b.x0 - left > self.layout.edge:
            return "me"
        if b.x0 - left <= self.layout.edge:
            return "them"
        return None
