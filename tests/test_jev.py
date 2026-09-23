import json

import httpx
import pytest

from chat_jev.jev import JevClient, JevError, choice, noul
from chat_jev.judge import Message, build_state, judge, parse_answers


def _transport(handler):
    return httpx.MockTransport(handler)


def test_typesafe_flavor_posts_systemone_and_returns_answers():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"model": "typesafe-ai/jev", "answers": {
            "q": {"type": "noul", "noul": 0.91}}, "usage": {"input_tokens": 1, "output_tokens": 1}})

    c = JevClient("k", base_url="https://ai-gateway.vercel.sh/typesafe", model="typesafe-ai/jev",
                  transport=_transport(handler))
    ans = c.evaluate("hi", {"q": noul("x?")})
    assert seen["url"] == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "typesafe-ai/jev"
    assert seen["body"]["questions"]["q"]["type"] == "noul"
    assert ans["q"]["noul"] == 0.91


def test_vercel_native_flavor_translates_boolean():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"answers": {
            "q": {"type": "boolean", "probability": 0.2},
            "c": {"type": "choice", "choice": "a", "probabilities": {"a": 0.7, "b": 0.3}}}})

    c = JevClient("k", base_url="https://ai-gateway.vercel.sh", flavor="vercel-native", transport=_transport(handler))
    ans = c.evaluate("hi", {"q": noul("x?"), "c": choice("y?", {"a": "", "b": ""})})
    assert seen["url"] == "https://ai-gateway.vercel.sh/v1/evaluate"
    assert seen["body"]["questions"]["q"]["type"] == "boolean"
    assert ans["q"] == {"type": "noul", "noul": 0.2}
    assert ans["c"]["choice"] == "a"


def test_http_error_raises_jev_error():
    c = JevClient("k", transport=_transport(lambda r: httpx.Response(401, json={"message": "bad key"})))
    with pytest.raises(JevError, match="401"):
        c.evaluate("hi", {"q": noul("x?")})


def test_missing_key_raises():
    with pytest.raises(JevError):
        JevClient("")


def test_build_state_labels_and_order():
    st = build_state([Message("me", "今晚吃什么"), Message("them", "随便")], Message("them", "你定吧"), relation="女朋友")
    assert st["历史消息"] == [{"发送者": "我", "内容": "今晚吃什么"}, {"发送者": "对方", "内容": "随便"}]
    assert st["待判断消息"] == {"发送者": "对方", "内容": "你定吧"}
    assert "女朋友" in st["背景"]


def test_parse_answers_threshold_and_intent():
    ans = {"literal": {"type": "noul", "noul": 0.3},
           "intent": {"type": "choice", "choice": "反话赌气", "probabilities": {"反话赌气": 0.6, "字面意思": 0.4}}}
    v = parse_answers(ans, threshold=0.5)
    assert v.label == "no" and v.intent == "反话赌气" and v.intent_probs["反话赌气"] == 0.6
    assert parse_answers(ans, threshold=0.25).label == "yes"


def test_judge_end_to_end_truncates_history():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"answers": {
            "literal": {"type": "noul", "noul": 0.8},
            "intent": {"type": "choice", "choice": "字面意思", "probabilities": {"字面意思": 0.8}}}})

    c = JevClient("k", transport=_transport(handler))
    hist = [Message("me", f"m{i}") for i in range(30)]
    v = judge(c, hist, Message("them", "好的"), history_size=5)
    assert v.label == "yes"
    assert len(seen["body"]["state"]["历史消息"]) == 5
    assert set(seen["body"]["questions"]) == {"literal", "intent"}


def test_build_state_group_mode_changes_background_and_keeps_names():
    hist = [Message("them", "在吗", name="A"), Message("them", "+1", name="B")]
    st = build_state(hist, Message("them", "不知道", name="A"), relation="女朋友", group=True)
    assert "群聊" in st["背景"] and "女朋友" not in st["背景"]
    assert [m["发送者"] for m in st["历史消息"]] == ["对方（A）", "对方（B）"]
    assert st["待判断消息"]["发送者"] == "对方（A）"
    # 私聊仍然提关系
    assert "女朋友" in build_state(hist, hist[0], relation="女朋友")["背景"]


def test_dotenv_strips_inline_comments_and_keeps_shell_values(tmp_path, monkeypatch):
    from chat_jev.config import load_dotenv
    env = tmp_path / ".env"
    env.write_text('JEV_THRESHOLD=0.7   # 阈值\nJEV_RELATION="女朋友 # 不是注释"\nAI_GATEWAY_API_KEY=\nLLM_API_KEY=abc\n', encoding="utf-8")
    monkeypatch.delenv("JEV_THRESHOLD", raising=False)
    monkeypatch.delenv("JEV_RELATION", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "from-shell")
    load_dotenv(env)
    import os
    assert os.environ["JEV_THRESHOLD"] == "0.7"
    assert os.environ["JEV_RELATION"] == "女朋友 # 不是注释"
    assert os.environ["AI_GATEWAY_API_KEY"] == "from-shell"
    assert os.environ["LLM_API_KEY"] == "abc"


def test_write_env_updates_in_place(tmp_path):
    from chat_jev.config import parse_env, write_env
    env = tmp_path / ".env"
    env.write_text("# 注释\nJEV_BACKEND=vercel\nAI_GATEWAY_API_KEY=\nJEV_RELATION=女朋友   # 关系\n# JEV_API_KEY=\n# LLM_BASE_URL=https://x\n")
    write_env(env, {"AI_GATEWAY_API_KEY": "sk-1", "JEV_RELATION": "男朋友", "JEV_API_KEY": "",
                    "LLM_BASE_URL": "https://y", "LLM_MODEL": "a b"})
    text = env.read_text()
    assert text.startswith("# 注释\nJEV_BACKEND=vercel\nAI_GATEWAY_API_KEY=sk-1\nJEV_RELATION=男朋友   # 关系\n# JEV_API_KEY=\n")
    assert "LLM_BASE_URL=https://y" in text and 'LLM_MODEL="a b"' in text
    assert parse_env(env)["LLM_MODEL"] == "a b"
    assert env.stat().st_mode & 0o777 == 0o600
