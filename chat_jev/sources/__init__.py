"""消息来源。每个来源实现 poll()，返回自上次调用以来新出现的消息（按时间顺序）。"""

from .ax import AppSource
from .base import Source
from .clipboard import ClipboardSource

__all__ = ["AppSource", "ClipboardSource", "Source"]
