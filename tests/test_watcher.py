"""主循环：假适配器喂快照，假 Jev 记录请求，检查上下文和输出。"""

import io
import json

import httpx

from chat_jev.app import Watcher
from chat_jev.config import Settings
from chat_jev.jev import JevClient
from chat_jev.judge import Message
from chat_jev.sources.ax import AppSource, Row, Snapshot


class FakeAdapter:
    bundle_id = "fake"

    def __init__(self, frames):
        self.frames = list(frames)

    def attach(self, app_el, pid):
        pass

    def read(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def make_source(frames):
    src = AppSource.__new__(AppSource)
    src.app, src.adapter, src.contact, src.only_when_frontmost = "fake", FakeAdapter(frames), None, False
    src._prev, src.last_contact = None, ""
    src._attach = lambda: True          # 跳过真实进程查找
    return src


def settings():
    return Settings(backend="vercel", base_url="https://x", api_key="k", model="m",
                    threshold=0.5, relation="女朋友", history_size=12, timeout=5,
                    llm_api_key="", llm_model="m", llm_base_url="", llm_timeout=5, llm_flavor="anthropic")


def test_new_them_message_is_judged_with_context():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "literal": {"type": "noul", "noul": 0.2},
            "intent": {"type": "choice", "choice": "反话赌气", "probabilities": {"反话赌气": 0.7, "字面意思": 0.3}}}})

    base = [Row("me", "", "今晚加班"), Row("them", "", "哦")]
    frames = [Snapshot("她", base),
              Snapshot("她", base + [Row("me", "", "别生气"), Row("them", "", "没事，你忙吧")])]
    src = make_source(frames)
    out = io.StringIO()
    w = Watcher(settings(), src, JevClient("k", transport=httpx.MockTransport(handler)), out=out, sync=True,
                history_seed=[Message("me", "今晚加班"), Message("them", "哦")])
    src.poll()                # 基线
    w.tick()                  # 第二帧：两条新消息，只有对方那条要判
    assert len(calls) == 1
    state = calls[0]["state"]
    assert state["待判断消息"]["内容"] == "没事，你忙吧"
    assert [m["内容"] for m in state["历史消息"]] == ["今晚加班", "哦", "别生气"]
    assert out.getvalue().startswith("NO  表里一致  20%  → 反话赌气 70%")


def test_own_messages_are_not_judged():
    calls = []
    handler = lambda req: (calls.append(1), httpx.Response(200, json={"answers": {}}))[1]
    base = [Row("them", "", "在吗")]
    src = make_source([Snapshot("她", base), Snapshot("她", base + [Row("me", "", "在")])])
    w = Watcher(settings(), src, JevClient("k", transport=httpx.MockTransport(handler)), out=io.StringIO(), sync=True)
    src.poll(); w.tick()
    assert calls == []


def test_group_flag_from_source_reaches_state():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"literal": {"type": "noul", "noul": 0.9},
                                                     "intent": {"type": "choice", "choice": "字面意思", "probabilities": {}}}})

    base = [Row("them", "A", "在吗")]
    frames = [Snapshot("群", base, is_group=True), Snapshot("群", base + [Row("them", "B", "不知道")], is_group=True)]
    src = make_source(frames)
    w = Watcher(settings(), src, JevClient("k", transport=httpx.MockTransport(handler)), out=io.StringIO(), sync=True)
    src.poll(); w.tick()
    assert "群聊" in calls[0]["state"]["背景"]
    assert calls[0]["state"]["待判断消息"]["发送者"] == "对方（B）"



class FakeLLM:
    """不走网络：记录收到的 prompt，返回固定的候选 JSON。"""

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, system, prompt, max_tokens=1024):
        self.prompts.append(prompt)
        return self.reply


def test_actions_pipeline_llm_then_jev():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        if "action" in body["questions"]:
            opts = list(body["questions"]["action"]["criteria"])
            probs = {o: (0.7 if i == 0 else 0.3 / (len(opts) - 1)) for i, o in enumerate(opts)}
            return httpx.Response(200, json={"answers": {"action": {
                "type": "choice", "choice": opts[0], "probabilities": probs, "confidence": 0.5}}})
        return httpx.Response(200, json={"answers": {
            "literal": {"type": "noul", "noul": 0.2},
            "intent": {"type": "choice", "choice": "反话赌气", "probabilities": {"反话赌气": 0.8}}}})

    llm = FakeLLM('```json\n[{"label": "先哄一句", "desc": "承认没陪到她"}, {"label": "直接问", "desc": "问是不是不高兴"}, '
                  '{"label": "先不回", "desc": "晚点打电话"}]\n```')
    base = [Row("me", "", "今晚加班")]
    src = make_source([Snapshot("她", base), Snapshot("她", base + [Row("them", "", "没事，你忙吧")])])
    out = io.StringIO()
    w = Watcher(settings(), src, JevClient("k", transport=httpx.MockTransport(handler)), out=out, sync=True, llm=llm)
    src.poll(); w.tick()

    assert len(calls) == 2                                   # 一次判别 + 一次打分
    assert "表里一致的概率 20%" in llm.prompts[0] and "反话赌气" in llm.prompts[0]
    action_q = calls[1]["questions"]["action"]
    assert action_q["type"] == "choice" and set(action_q["criteria"]) == {"先哄一句", "直接问", "先不回"}
    assert calls[1]["state"]["判别结果"]["最可能的真实意图"] == "反话赌气"
    text = out.getvalue()
    assert "NO  表里一致  20%" in text and "→ 建议：先哄一句 70%" in text
    assert w.last[2].best == "先哄一句"


def test_llm_failure_keeps_verdict():
    handler = lambda req: httpx.Response(200, json={"answers": {
        "literal": {"type": "noul", "noul": 0.9}, "intent": {"type": "choice", "choice": "字面意思", "probabilities": {}}}})
    base = [Row("me", "", "hi")]
    src = make_source([Snapshot("她", base), Snapshot("她", base + [Row("them", "", "好")])])
    out = io.StringIO()
    w = Watcher(settings(), src, JevClient("k", transport=httpx.MockTransport(handler)), out=out, sync=True,
                llm=FakeLLM("这不是 JSON"))
    src.poll(); w.tick()
    assert out.getvalue().startswith("YES") and "建议" not in out.getvalue()
