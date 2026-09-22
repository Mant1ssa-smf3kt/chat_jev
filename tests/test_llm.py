import pytest

from chat_jev.llm import LLMError, build_prompt, parse_candidates
from chat_jev.judge import Message, Verdict


def test_parse_candidates_strips_fences_and_dedupes():
    text = "好的，方案如下：\n```json\n[{\"label\":\"A\",\"desc\":\"a\"},{\"label\":\"A\",\"desc\":\"dup\"},{\"label\":\"B\"},\"junk\",{\"label\":\"\"}]\n```"
    c = parse_candidates(text)
    assert [(x.label, x.desc) for x in c] == [("A", "a"), ("B", "B")]


def test_parse_candidates_limit_and_errors():
    many = "[" + ",".join(f'{{"label":"o{i}","desc":"d"}}' for i in range(9)) + "]"
    assert len(parse_candidates(many, limit=5)) == 5
    with pytest.raises(LLMError):
        parse_candidates("没有数组")
    with pytest.raises(LLMError):
        parse_candidates('[{"label":"only one","desc":"x"}]')


def test_build_prompt_mentions_context_and_verdict():
    v = Verdict(False, 0.3, "试探", {"试探": 0.6, "字面意思": 0.3})
    p = build_prompt([Message("me", "今晚加班"), Message("them", "哦", name="她")], Message("them", "随便"), v,
                     relation="女朋友", group=False)
    assert "我和女朋友的私聊" in p and "我：今晚加班" in p and "对方（她）：哦" in p
    assert "刚收到的消息：对方：随便" in p and "试探 60%" in p
    assert "群聊" in build_prompt([], Message("them", "x"), v, relation="女朋友", group=True)


def test_openai_flavor_posts_chat_completions():
    import httpx
    from chat_jev.llm import LLMClient
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = str(req.url), req.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]})

    c = LLMClient("k", "m", base_url="https://x/v1", flavor="openai")
    c._http = httpx.Client(base_url="https://x/v1", transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer k"})
    assert c.complete("sys", "hi") == "[]"
    assert seen["url"] == "https://x/v1/chat/completions" and b'"role":"system"' in seen["body"]
