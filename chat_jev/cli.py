"""命令行入口：

  chat-jev judge "她说的话" --ctx "我: 今晚吃什么" --ctx "她: 随便"     单条判别
  chat-jev watch --app qq                                              实时监听（浮窗）
  chat-jev watch --source clipboard --no-overlay                       复制即判别（终端输出）
  chat-jev snapshot --app qq                                           打印当前解析到的消息（调试）
  chat-jev dump --app wechat                                           打印辅助功能树（适配新版本用）
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load_settings
from .jev import JevClient
from .judge import Message, judge


def _client(settings):
    return JevClient(api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
                     flavor=settings.flavor, timeout=settings.timeout)


def _llm(settings, disabled: bool):
    """配了 LLM_API_KEY 就自动启用「下一步建议」；--no-actions 关掉。"""
    if disabled:
        return None
    if not settings.llm_enabled:
        print("[llm] 没配 LLM_API_KEY，不生成「下一步建议」。在 .env 里填上就会自动开启。", file=sys.stderr)
        return None
    from .llm import LLMClient
    return LLMClient(api_key=settings.llm_api_key, model=settings.llm_model,
                     base_url=settings.llm_base_url or None, timeout=settings.llm_timeout,
                     flavor=settings.llm_flavor)


def _parse_ctx(items: list[str]) -> list[Message]:
    out: list[Message] = []
    for raw in items:
        who, sep, text = raw.partition(":")
        if not sep:
            who, sep, text = raw.partition("：")
        who = who.strip()
        if who in ("我", "me", "I"):
            out.append(Message("me", text.strip()))
        else:
            out.append(Message("them", text.strip()))
    return out


def cmd_judge(args, settings) -> int:
    client = _client(settings)
    llm = _llm(settings, args.no_actions)
    history, target = _parse_ctx(args.ctx), Message("them", args.text)
    v = judge(client, history, target, relation=settings.relation, threshold=settings.threshold,
              history_size=settings.history_size, group=args.group)
    plan = None
    if llm is not None:
        from .judge import rank_actions
        from .llm import propose_actions
        cands = propose_actions(llm, history, target, v, relation=settings.relation, group=args.group)
        plan = rank_actions(client, history, target, v, cands, relation=settings.relation,
                            history_size=settings.history_size, group=args.group)
    if args.json:
        out = {"verdict": v.label, "p_literal": v.p_literal, "intent": v.intent, "intent_probs": v.intent_probs}
        if plan is not None:
            out["actions"] = {"best": plan.best, "probs": plan.probs, "descs": plan.descs, "confidence": plan.confidence}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        from .app import format_plan, format_verdict
        print(format_verdict(v, args.text))
        if plan is not None:
            print(format_plan(plan))
    return 0


def _check_permissions(app: str) -> bool:
    from . import ax, capture
    if app == "wechat":
        if not capture.ensure_screen_access(prompt=True):
            print("微信走截图 OCR，需要「屏幕录制」权限：系统设置 → 隐私与安全性 → 屏幕与系统音频录制，"
                  "把你的终端加进去，重开终端后重试。", file=sys.stderr)
            return False
        return True
    if not ax.ensure_trusted(prompt=True):
        print("需要「辅助功能」权限：系统设置 → 隐私与安全性 → 辅助功能，把你的终端加进去后重试。", file=sys.stderr)
        return False
    return True


def cmd_watch(args, settings) -> int:
    from .app import Watcher, build_source, run_gui, run_terminal

    if args.source == "app" and not _check_permissions(args.app):
        return 2
    source = build_source(args.source, args.app, args.contact, args.frontmost)
    seed = None
    if args.source == "app":
        snap = source.current()
        if snap is None:
            print(f"[watch] 暂时没读到 {args.app} 的聊天窗口（应用没开 / 没登录 / 没打开聊天 / 首次截图初始化慢），会继续等。", file=sys.stderr)
        else:
            from .sources.ax import NON_TEXT
            seed = [Message(r.sender, r.text, r.name) for r in snap.rows if r.text and r.text != NON_TEXT]
            source.poll()          # 建立基线
            print(f"[watch] 当前聊天：{snap.contact or '?'}，已载入 {len(seed)} 条上下文", file=sys.stderr)
    watcher = Watcher(settings, source, _client(settings), history_seed=seed, llm=_llm(settings, args.no_actions))
    if args.no_overlay:
        run_terminal(watcher, args.interval)
    else:
        run_gui(watcher, args.interval, args.hide_after)
    return 0


def cmd_snapshot(args, settings) -> int:
    from .sources import AppSource
    if not _check_permissions(args.app):
        return 2
    src = AppSource(args.app)
    snap = src.current()
    if snap is None:
        print("没读到聊天窗口（应用没开、没登录，或没打开任何聊天）", file=sys.stderr)
        return 1
    print(f"聊天对象: {snap.contact!r}  {'群聊' if snap.is_group else '私聊'}  共 {len(snap.rows)} 条")
    for r in snap.rows:
        print(f"  [{r.sender:4}] {r.name + ': ' if r.name else ''}{r.text}")
    if args.boxes and hasattr(src.adapter, "last_boxes"):
        print("\nOCR 文本框（窗口内 pt 坐标，原点左上）：")
        for b in src.adapter.last_boxes:
            print(f"  x[{b.x0:5.0f}-{b.x1:5.0f}] y[{b.y0:5.0f}-{b.y1:5.0f}] h={b.h:4.1f}  {b.text!r}")
    if args.save and hasattr(src.adapter, "save_last_image"):
        src.adapter.save_last_image(args.save)
        print(f"截图已存到 {args.save}")
    return 0


def cmd_dump(args, settings) -> int:
    from . import ax
    from .sources.ax import BUNDLE_IDS
    bundle = BUNDLE_IDS.get(args.app, args.app)
    app = ax.running_app(bundle)
    if app is None:
        print(f"{bundle} 没在运行", file=sys.stderr)
        return 1
    el = ax.app_element(app.processIdentifier())
    ax.enable_chromium_accessibility(el)
    budget = args.limit
    for win in ax.attr(el, "AXWindows") or []:
        for node, depth in ax.walk(win, args.depth):
            if budget <= 0:
                print("... (加大 --limit 看更多)")
                return 0
            budget -= 1
            parts = []
            for k in ("AXTitle", "AXValue", "AXDescription", "AXIdentifier", "AXDOMClassList"):
                v = ax.attr(node, k)
                if v not in (None, "", []):
                    parts.append(f"{k[2:]}={str(v)[:80]!r}")
            sub = ax.attr(node, "AXSubrole")
            pos, sz = ax.position(node), ax.size(node)
            geo = f"@({pos[0]:.0f},{pos[1]:.0f}) {sz[0]:.0f}x{sz[1]:.0f}" if pos and sz else ""
            print("  " * depth + f"{ax.role(node)}{'/' + sub if sub else ''} {geo} " + " ".join(parts))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="chat-jev", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", help="判别一句话")
    j.add_argument("text", help="对方说的话")
    j.add_argument("--ctx", action="append", default=[], help='上下文，形如 "我: ..." 或 "她: ..."，可多次')
    j.add_argument("--json", action="store_true")
    j.add_argument("--group", action="store_true", help="按群聊语境判别")
    j.add_argument("--no-actions", action="store_true", help="不生成「接下来该怎么做」（配了 LLM_API_KEY 时默认生成）")
    j.set_defaults(fn=cmd_judge)

    w = sub.add_parser("watch", help="实时监听微信/QQ")
    w.add_argument("--app", default="qq", help="qq | wechat | <bundle id>")
    w.add_argument("--source", default="app", choices=["app", "clipboard"],
                   help="app = 读应用窗口（QQ 走辅助功能，微信走 OCR）；clipboard = 复制即判别")
    w.add_argument("--contact", help="只看这个聊天对象（名字包含匹配）")
    w.add_argument("--frontmost", action="store_true", help="只在应用处于前台时读取")
    w.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒")
    w.add_argument("--hide-after", type=float, default=8.0, help="浮窗几秒后自动隐藏，0 = 不隐藏")
    w.add_argument("--no-overlay", action="store_true", help="不显示浮窗，只在终端打印")
    w.add_argument("--no-actions", action="store_true", help="不生成「接下来该怎么做」（配了 LLM_API_KEY 时默认生成）")
    w.set_defaults(fn=cmd_watch)

    s = sub.add_parser("snapshot", help="打印当前解析到的消息（调试 / 校准布局）")
    s.add_argument("--app", default="qq")
    s.add_argument("--boxes", action="store_true", help="OCR 来源：同时打印所有文本框坐标")
    s.add_argument("--save", help="OCR 来源：把截图存到这个 PNG 路径")
    s.set_defaults(fn=cmd_snapshot)

    d = sub.add_parser("dump", help="打印辅助功能树（调试）")
    d.add_argument("--app", default="qq")
    d.add_argument("--depth", type=int, default=60)
    d.add_argument("--limit", type=int, default=3000)
    d.set_defaults(fn=cmd_dump)

    args = p.parse_args(argv)
    settings = load_settings()
    return args.fn(args, settings)


if __name__ == "__main__":
    sys.exit(main())
