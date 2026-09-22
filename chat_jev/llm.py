"""文本 LLM：负责"发散"——根据对话和 Jev 的判别结果，想出几个"接下来该怎么做"的候选。

候选本身不带概率；概率分布由 Jev 在这些候选上打（见 judge.rank_actions）。

======================================================================
接 LLM 只看 LLMClient，契约就一条：complete(system, prompt) -> 纯文本。
两种请求格式（LLM_FLAVOR）：
  anthropic（默认） Anthropic Messages 格式，走官方 SDK。base_url 可指向任何兼容端点：
                    直连 Anthropic（留空）/ Vercel AI Gateway https://ai-gateway.vercel.sh
                    / DeepSeek https://api.deepseek.com/anthropic 等
  openai            OpenAI chat/completions 格式，用 httpx 直接 POST，适配没有 Anthropic 兼容端点的 provider
换成别的协议：再加一个 _complete_xxx 方法即可。
======================================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .judge import Message, Verdict


@dataclass(frozen=True)
class Candidate:
    label: str      # 短标签，会成为 Jev choice 的选项名，≤ 12 字
    desc: str       # 一句话说明怎么做 / 为什么


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str, model: str, base_url: str | None = None, timeout: float = 30.0,
                 flavor: str = "anthropic") -> None:
        if not api_key:
            raise LLMError("缺少 LLM_API_KEY：在 .env 里填上才能启用「下一步建议」")
        if flavor not in ("anthropic", "openai"):
            raise LLMError(f"未知 LLM_FLAVOR={flavor!r}，可选 anthropic / openai")
        self.model = model
        self.flavor = flavor
        self.timeout = timeout
        if flavor == "anthropic":
            import anthropic
            self._anthropic = anthropic
            self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url or None, timeout=timeout)
        else:
            import httpx
            self._http = httpx.Client(
                base_url=(base_url or "https://api.openai.com/v1").rstrip("/"), timeout=timeout,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        if self.flavor == "anthropic":
            return self._complete_anthropic(system, prompt, max_tokens)
        return self._complete_openai(system, prompt, max_tokens)

    # ---- Anthropic Messages 格式 -----------------------------------------------------
    def _complete_anthropic(self, system: str, prompt: str, max_tokens: int) -> str:
        if "claude" in self.model.lower():
            # Claude：保留自适应思考，用低 effort 换速度（4.6+ 不建议整个关掉 thinking）
            extra = {"output_config": {"effort": "low"}}
        else:
            # 其它走 Anthropic 兼容端点的模型（DeepSeek 等）：关掉思考，快且省 token
            extra = {"thinking": {"type": "disabled"}}
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}], **extra)
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"LLM 返回 {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"连接 LLM 失败: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("LLM 拒绝了这次请求")
        return "".join(b.text for b in resp.content if b.type == "text")

    # ---- OpenAI chat/completions 格式 -------------------------------------------------
    def _complete_openai(self, system: str, prompt: str, max_tokens: int) -> str:
        import httpx
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        try:
            r = self._http.post("/chat/completions", json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"连接 LLM 失败: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"LLM 返回 {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMError(f"LLM 响应格式不对: {r.text[:200]}") from e


SYSTEM_PROMPT = (
    "你是一个帮使用者处理即时聊天的助手。使用者收到了一条消息，已经有一个判别模型判断了这句话"
    "是不是字面意思、真实意图是什么。你的任务：给出使用者接下来可以采取的 3 到 5 个**具体、可执行、互相不同**的回应方案。"
    "每个方案一个短标签（不超过 12 个字，能当选项名）和一句话说明（怎么做、为什么）。"
    "方案要覆盖不同方向（比如：直接回应字面 / 先安抚再解释 / 反问确认 / 转移话题 / 暂时不回）。"
    "只输出一个 JSON 数组，不要任何别的文字：[{\"label\": \"...\", \"desc\": \"...\"}, ...]"
)


def build_prompt(history: list[Message], target: Message, verdict: Verdict, *, relation: str, group: bool) -> str:
    who = {"me": "我", "them": "对方"}
    lines = [f"{who[m.sender]}{'（' + m.name + '）' if m.name and m.sender == 'them' else ''}：{m.text}" for m in history]
    scene = "这是一个群聊，'对方'是不同的群友。" if group else f"这是我和{relation}的私聊。"
    intents = "，".join(f"{k} {v * 100:.0f}%" for k, v in sorted(verdict.intent_probs.items(), key=lambda kv: -kv[1])[:3])
    return (
        f"{scene}\n\n最近的对话：\n" + ("\n".join(lines) if lines else "（无）") +
        f"\n\n刚收到的消息：{who[target.sender]}{'（' + target.name + '）' if target.name else ''}：{target.text}"
        f"\n\n判别结果：表里一致的概率 {verdict.p_literal * 100:.0f}%（{'yes' if verdict.literal else 'no'}），"
        f"最可能的真实意图：{verdict.intent}。意图分布：{intents or '无'}。"
        "\n\n给出接下来的回应方案。"
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_candidates(text: str, limit: int = 5) -> list[Candidate]:
    """容错解析：去掉代码围栏、截取第一个 [...]，跳过坏项，去重。"""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        raise LLMError(f"LLM 没有返回 JSON 数组: {text[:120]!r}")
    try:
        items = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM 返回的 JSON 解析失败: {e}") from e
    out: list[Candidate] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        label = str(it.get("label", "")).strip()[:20]
        desc = str(it.get("desc", "")).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(Candidate(label, desc or label))
        if len(out) >= limit:
            break
    if len(out) < 2:
        raise LLMError("LLM 给出的可用候选不足 2 个")
    return out


def propose_actions(llm: LLMClient, history: list[Message], target: Message, verdict: Verdict,
                    *, relation: str = "女朋友", group: bool = False) -> list[Candidate]:
    text = llm.complete(SYSTEM_PROMPT, build_prompt(history, target, verdict, relation=relation, group=group))
    return parse_candidates(text)
