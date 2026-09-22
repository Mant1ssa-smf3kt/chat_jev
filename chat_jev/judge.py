"""判别逻辑：把一段对话变成 Jev 的 state + questions，再把 answers 变成 yes/no。

核心问题只有一个 noul：`待判断消息` 的真实意图是否就是字面意思。
顺带问一个 choice（真实意图属于哪类），判成 no 的时候能看出对方到底想说什么。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .jev import JevClient, choice, noul

Sender = Literal["me", "them"]


@dataclass(frozen=True)
class Message:
    sender: Sender
    text: str
    name: str = ""      # 发送者显示名，群聊里用来区分是谁说的；拿不到就空


@dataclass(frozen=True)
class Verdict:
    literal: bool               # True = yes（表里一致），False = no
    p_literal: float            # 表里一致的概率 0~1
    intent: str                 # 最可能的真实意图类别
    intent_probs: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "yes" if self.literal else "no"


@dataclass(frozen=True)
class ActionPlan:
    """"接下来该怎么做"的概率分布：候选由 LLM 提出，分布由 Jev 打。"""
    best: str
    probs: dict[str, float]            # label -> 概率，按概率降序
    descs: dict[str, str]              # label -> 说明
    confidence: float | None = None

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.probs.items(), key=lambda kv: -kv[1])


INTENTS: dict[str, str] = {
    "字面意思": "就是字面上说的意思，没有言外之意",
    "反话赌气": "嘴上说没事、随便、不用、你忙吧，实际上有情绪、在生气或失望",
    "试探": "想看你的反应或态度，话本身不是重点",
    "撒娇求关注": "希望你多哄哄、多关心、多陪伴",
    "暗示需求": "拐着弯希望你做某件事、说某句话或买某样东西",
    "敷衍冷淡": "不想多聊，回应敷衍，可能在不满或疲惫",
    "开玩笑调侃": "玩笑或调侃，不是认真的字面意思",
}

QUESTIONS: dict[str, Any] = {
    "literal": noul(
        "看 `待判断消息`，结合 `历史消息` 的上下文和 `背景`。"
        "对方想表达的真实意思，是否就是这句话的字面意思（表里一致）？",
        criteria={
            "true": "字面意思就是真实意图：陈述事实、直接表达需求或情绪，"
                    "没有反话、暗示、试探或需要揣摩的言外之意。",
            "false": "表里不一：说的和想的不一样。例如反话（说没事其实有事）、赌气、"
                     "试探你的反应、撒娇求关注、暗示想要某样东西或某种行动、敷衍冷淡、话里有话。",
        },
    ),
    "intent": choice("`待判断消息` 背后最主要的真实意图是哪一类？", INTENTS),
}


def build_state(history: list[Message], target: Message, *, relation: str, group: bool = False,
                me: str = "我", them: str = "对方") -> dict[str, Any]:
    who = {"me": me, "them": them}

    def label(m: Message) -> str:
        return f"{who[m.sender]}（{m.name}）" if m.name and m.sender == "them" else who[m.sender]

    if group:
        background = (f"以下是一个群聊的消息记录，按时间先后排列。“{me}”指使用者本人；"
                      f"“{them}（昵称）”是不同的群友，括号里是各自的昵称，不要把他们当成同一个人。"
                      f"待判断的是 `待判断消息` 里那位群友说的话。")
    else:
        background = f"以下是我和{relation}之间的私聊记录，按时间先后排列。“{them}”指{relation}，“{me}”指使用者本人。"
    return {
        "背景": background,
        "历史消息": [{"发送者": label(m), "内容": m.text} for m in history],
        "待判断消息": {"发送者": label(target), "内容": target.text},
    }


def parse_answers(answers: dict[str, Any], threshold: float) -> Verdict:
    lit = answers.get("literal", {})
    p = float(lit.get("noul", 0.0))
    it = answers.get("intent", {})
    probs = {k: float(v) for k, v in (it.get("probabilities") or {}).items()}
    intent = it.get("choice") or (max(probs, key=probs.get) if probs else "未知")
    literal = p >= threshold
    if not literal and intent == "字面意思" and probs:
        # noul 说表里不一，choice 却选了字面意思：两个问题独立评估，偶有分歧。
        # 这时展示最可能的非字面意图，对使用者更有用。
        others = {k: v for k, v in probs.items() if k != "字面意思"}
        if others:
            intent = max(others, key=others.get)
    return Verdict(literal=literal, p_literal=p, intent=intent, intent_probs=probs, raw=answers)


def judge(
    client: JevClient,
    history: list[Message],
    target: Message,
    *,
    relation: str = "女朋友",
    threshold: float = 0.5,
    history_size: int = 12,
    group: bool = False,
) -> Verdict:
    """对 target 这一条消息给出 yes/no。history 是它之前的对话（不含 target）。group=True 表示群聊。"""
    state = build_state(history[-history_size:] if history_size else history, target,
                        relation=relation, group=group)
    answers = client.evaluate(state, QUESTIONS)
    return parse_answers(answers, threshold)


def rank_actions(
    client: JevClient,
    history: list[Message],
    target: Message,
    verdict: Verdict,
    candidates: list,                  # list[llm.Candidate]，这里不 import 以免循环依赖
    *,
    relation: str = "女朋友",
    history_size: int = 12,
    group: bool = False,
) -> ActionPlan:
    """把 LLM 给的候选交给 Jev，得到"我接下来最应该怎么做"的概率分布。"""
    state = build_state(history[-history_size:] if history_size else history, target,
                        relation=relation, group=group)
    state["判别结果"] = {
        "表里一致概率": round(verdict.p_literal, 2),
        "最可能的真实意图": verdict.intent,
    }
    descs = {c.label: c.desc for c in candidates}
    answers = client.evaluate(state, {
        "action": choice(
            "结合 `历史消息`、`待判断消息` 和 `判别结果`，作为“我”，接下来最应该采取哪个回应方案？"
            "选最能照顾对方真实意图、又不会把事情弄僵的那个。",
            descs,
        ),
    })
    a = answers.get("action", {})
    probs = {k: float(v) for k, v in (a.get("probabilities") or {}).items()}
    best = a.get("choice") or (max(probs, key=probs.get) if probs else next(iter(descs)))
    conf = a.get("confidence")
    return ActionPlan(best=best, probs=dict(sorted(probs.items(), key=lambda kv: -kv[1])), descs=descs,
                      confidence=float(conf) if conf is not None else None)
