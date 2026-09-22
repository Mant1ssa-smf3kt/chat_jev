"""Jev 调用层。只做一件事：state + questions 进，answers 出。

两种请求格式：
  typesafe       POST {base_url}/v1/systemone    问题类型 noul/choice/score
                 适用于 api.typesafe.ai 和 ai-gateway.vercel.sh/typesafe
  vercel-native  POST {base_url}/v1/evaluate     问题类型 boolean/choice/score
                 返回 probability，这里统一转成 noul，上层不用关心
"""

from __future__ import annotations

from typing import Any

import httpx

Json = dict[str, Any]


class JevError(RuntimeError):
    pass


class JevClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ai-gateway.vercel.sh/typesafe",
        model: str = "typesafe-ai/jev",
        flavor: str = "typesafe",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise JevError("缺少 API key：请设置 JEV_API_KEY（或 AI_GATEWAY_API_KEY / TYPESAFE_API_KEY）")
        if flavor not in ("typesafe", "vercel-native"):
            raise JevError(f"未知 flavor: {flavor}")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.flavor = flavor
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            transport=transport,
        )

    # ---- public -----------------------------------------------------------

    def evaluate(self, state: Any, questions: Json) -> Json:
        """返回 TypeSafe 形状的 answers：{qid: {"type": "noul", "noul": p} | choice | score}"""
        if self.flavor == "vercel-native":
            url = f"{self.base_url}/v1/evaluate"
            body = {"model": self.model, "state": state, "questions": _to_vercel_questions(questions)}
        else:
            url = f"{self.base_url}/v1/systemone"
            body = {"model": self.model, "state": state, "questions": questions}

        try:
            resp = self._http.post(url, json=body)
        except httpx.HTTPError as e:
            raise JevError(f"请求 Jev 失败: {e}") from e
        if resp.status_code >= 400:
            raise JevError(f"Jev 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise JevError(f"响应缺少 answers: {data}")
        return _from_vercel_answers(answers) if self.flavor == "vercel-native" else answers

    def close(self) -> None:
        self._http.close()


# ---- 问题定义的小工具，和 TypeSafe SDK 的 Noul/Choice/Score 同形 ---------------

def noul(instructions: Any, criteria: dict[str, str] | None = None) -> Json:
    q: Json = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    return q


def choice(instructions: Any, criteria: dict[str, str]) -> Json:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: Any, criteria: list[str]) -> Json:
    return {"type": "score", "instructions": instructions, "criteria": criteria}


# ---- vercel-native 与 typesafe 之间的转换 ------------------------------------

def _to_vercel_questions(questions: Json) -> Json:
    out: Json = {}
    for qid, q in questions.items():
        q = dict(q)
        if q.get("type") == "noul":
            q["type"] = "boolean"
        out[qid] = q
    return out


def _from_vercel_answers(answers: Json) -> Json:
    out: Json = {}
    for qid, a in answers.items():
        a = dict(a)
        if a.get("type") == "boolean":
            a = {"type": "noul", "noul": a.get("probability")}
        out[qid] = a
    return out
