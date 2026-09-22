"""chat-jev: 用 Jev 判别聊天消息的表面意思和真实意图是否一致。"""

from .judge import Message, Verdict, judge
from .jev import JevClient

__all__ = ["JevClient", "Message", "Verdict", "judge"]
