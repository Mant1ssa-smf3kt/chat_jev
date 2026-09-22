from __future__ import annotations

from typing import Protocol

from ..judge import Message


class Source(Protocol):
    name: str

    def poll(self) -> list[Message]:
        """返回新消息（可能为空）。调用方负责按固定间隔轮询。"""
        ...
