"""剪贴板来源：在微信/QQ 里复制一条消息，就当成对方刚发来的这条来判别。

零权限、零风险的兜底方案；也可以用来手动喂上下文。
"""

from __future__ import annotations

from AppKit import NSPasteboard, NSPasteboardTypeString

from ..judge import Message


class ClipboardSource:
    name = "clipboard"
    last_contact = ""

    def __init__(self) -> None:
        self._pb = NSPasteboard.generalPasteboard()
        self._last_change = self._pb.changeCount()   # 启动时已有的内容不算

    def poll(self) -> list[Message]:
        change = self._pb.changeCount()
        if change == self._last_change:
            return []
        self._last_change = change
        text = self._pb.stringForType_(NSPasteboardTypeString)
        if not text or not text.strip():
            return []
        return [Message("them", text.strip())]
