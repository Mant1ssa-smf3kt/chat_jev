"""打包成 chat-jev.app 后的入口。

从 Finder 双击打开时没有终端：输出写进日志文件，配置从 ~/Library/Application Support/chat-jev/.env 读。
辅助功能权限授给 chat-jev.app 本身，不需要给终端。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from .config import CONFIG_DIR, CONFIG_FILE, load_dotenv, load_settings

LOG_FILE = Path.home() / "Library" / "Logs" / "chat-jev.log"


def _redirect_output() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = log


def _template() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = base / ".env.example"
    return path.read_text(encoding="utf-8") if path.is_file() else "AI_GATEWAY_API_KEY=\n"


def ensure_config() -> None:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(_template(), encoding="utf-8")
        CONFIG_FILE.chmod(0o600)                 # 里面是密钥，只给自己读


def open_config() -> None:
    ensure_config()
    subprocess.run(["open", "-e", str(CONFIG_FILE)], check=False)


def open_log() -> None:
    subprocess.run(["open", "-a", "Console", str(LOG_FILE)], check=False)


def selftest() -> int:
    """打包脚本用：确认冻结后的 app 能导入全部模块、读到配置模板，不弹任何权限框。"""
    import importlib
    for mod in ("app", "ax", "cli", "jev", "judge", "llm", "menubar", "overlay", "picker", "settings_window",
                "sources.ax", "sources.clipboard"):
        importlib.import_module(f"chat_jev.{mod}")
    assert "AI_GATEWAY_API_KEY" in _template(), "没打包进 .env.example"
    print("selftest ok")
    return 0


def main() -> int:
    if os.environ.get("CHAT_JEV_SELFTEST"):
        return selftest()
    _redirect_output()
    ensure_config()
    load_dotenv()
    if not load_settings().api_key:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        from .settings_window import SettingsWindow
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        if not SettingsWindow(first_run=True).run_modal():
            return 1                                 # 点了退出
        load_settings(override=True)
    from .cli import main as cli_main
    # 想改默认行为（只判点选、只看某个人……）就在配置里写 JEV_WATCH_ARGS="--pick-only --interval 0.5"
    extra = shlex.split(os.environ.get("JEV_WATCH_ARGS", ""))
    return cli_main(["watch", "--app", "qq", *extra])


if __name__ == "__main__":
    sys.exit(main())
