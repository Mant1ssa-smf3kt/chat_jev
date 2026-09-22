"""配置：全部来自环境变量，可选从项目根目录的 .env 读取。

后端切换只需要改三个值：

    JEV_BASE_URL   接口地址（默认 Vercel AI Gateway 的 TypeSafe 兼容端点）
    JEV_API_KEY    密钥（没设则依次找 AI_GATEWAY_API_KEY / TYPESAFE_API_KEY）
    JEV_MODEL      模型 ID（Vercel 上是 typesafe-ai/jev，TypeSafe 直连是 jev-latest）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 预置的两套后端，JEV_BACKEND=vercel|typesafe 可以一键切换
BACKENDS = {
    "vercel": {
        "base_url": "https://ai-gateway.vercel.sh/typesafe",
        "model": "typesafe-ai/jev",
        "key_envs": ("AI_GATEWAY_API_KEY",),
    },
    "vercel-native": {
        # Vercel 原生 /v1/evaluate，请求用 boolean 而不是 noul，JevClient 会做转换
        "base_url": "https://ai-gateway.vercel.sh",
        "model": "typesafe-ai/jev",
        "key_envs": ("AI_GATEWAY_API_KEY",),
    },
    "typesafe": {
        "base_url": "https://api.typesafe.ai",
        "model": "jev-latest",
        "key_envs": ("TYPESAFE_API_KEY",),
    },
}


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 读取：KEY=VALUE，一行一个，不覆盖已有环境变量。"""
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]                      # 带引号：原样取
        else:
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()   # 不带引号：去行内注释
        if value:
            os.environ.setdefault(key, value)        # 空值不写入，免得盖掉 shell 里的


@dataclass(frozen=True)
class Settings:
    backend: str
    base_url: str
    api_key: str
    model: str
    threshold: float          # noul >= threshold 视为"表里一致"(yes)
    relation: str             # 对方和我的关系，写进 state 的背景里
    history_size: int         # 送给 Jev 的上下文条数
    timeout: float
    # 文本 LLM（可选）：给"接下来该怎么做"提候选。留空 = 不启用。
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    llm_timeout: float
    llm_flavor: str           # anthropic | openai

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def flavor(self) -> str:
        return "vercel-native" if self.backend == "vercel-native" else "typesafe"


def load_settings() -> Settings:
    load_dotenv()
    backend = os.environ.get("JEV_BACKEND", "vercel")
    preset = BACKENDS.get(backend)
    if preset is None:
        raise SystemExit(f"未知的 JEV_BACKEND={backend!r}，可选: {', '.join(BACKENDS)}")

    api_key = os.environ.get("JEV_API_KEY", "")
    for env in preset["key_envs"]:
        api_key = api_key or os.environ.get(env, "")
    api_key = api_key or os.environ.get("AI_GATEWAY_API_KEY", "") or os.environ.get("TYPESAFE_API_KEY", "")

    return Settings(
        backend=backend,
        base_url=os.environ.get("JEV_BASE_URL", preset["base_url"]).rstrip("/"),
        api_key=api_key,
        model=os.environ.get("JEV_MODEL", preset["model"]),
        threshold=float(os.environ.get("JEV_THRESHOLD", "0.5")),
        relation=os.environ.get("JEV_RELATION", "女朋友"),
        history_size=int(os.environ.get("JEV_HISTORY", "12")),
        timeout=float(os.environ.get("JEV_TIMEOUT", "15")),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "claude-opus-5"),
        llm_base_url=os.environ.get("LLM_BASE_URL", ""),
        llm_timeout=float(os.environ.get("LLM_TIMEOUT", "30")),
        llm_flavor=os.environ.get("LLM_FLAVOR", "anthropic"),
    )
