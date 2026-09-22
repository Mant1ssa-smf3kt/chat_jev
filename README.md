# chat-jev

盯着桌面微信 / QQ 的聊天窗口，对方每发来一句话，就用 [Jev](https://typesafe.ai)（TypeSafe AI 的判别模型）判断：
**她想表达的意思是不是这句话的字面意思？** 表里一致 → `YES`，话里有话 → `NO`，顺带给出最可能的真实意图。

结果显示在屏幕右上角的浮窗里，也会打印在终端。程序不进 Dock，靠**菜单栏图标**（💬 气泡）确认它在跑：
图标旁会短暂显示最近一次的 YES / NO，点开菜单能看到正在盯哪个聊天、暂停 / 继续、退出。

```
NO  表里一致  44%  → 反话赌气 49%  |  没事，你忙吧
YES 表里一致  94%                  |  好呀，那我们七点在老地方见
```

## 原理

不注入、不读数据库、不改客户端，只做旁挂：

| 应用 | 读取方式 | 需要的权限 |
|---|---|---|
| QQ (NT 版, Electron) | macOS 辅助功能树。DOM class 直接标出自己/对方 | 辅助功能 |
| 微信 4.x | 截窗口图 + 系统 Vision OCR（离线）。气泡在左=对方，在右=我 | 屏幕录制 |
| 任何应用 | 剪贴板：复制一句话就判别 | 无 |

判别只把**文字**发给 Jev（最近 12 条上下文 + 待判断的这条），截图不出本机。

## 安装

```bash
cd chat_jev
uv sync
cp .env.example .env    # 填 AI_GATEWAY_API_KEY（或 TYPESAFE_API_KEY）
```

需要 macOS 14+、Python 3.13、[uv](https://docs.astral.sh/uv/)。

## 用法

```bash
# 单句判别（带上下文）
uv run chat-jev judge "没事，你忙吧" --ctx "我: 今晚加班，不能陪你吃饭了"

# 实时监听 QQ（浮窗）
uv run chat-jev watch --app qq

# 实时监听微信，只看某个人
uv run chat-jev watch --app wechat --contact 她的昵称

# 不要浮窗，只打终端
uv run chat-jev watch --app qq --no-overlay

# 复制即判别（任何应用都行）
uv run chat-jev watch --source clipboard

# 调试：看看现在解析出了什么
uv run chat-jev snapshot --app wechat --boxes --save /tmp/wx.png
uv run chat-jev dump --app qq | less
```

第一次运行会弹系统权限请求。**权限是给启动它的终端的**（Terminal / iTerm / Ghostty…），
授权后要重开终端再跑。

`watch` 启动时浮窗会弹一下"chat-jev 已启动"，菜单栏出现气泡图标。它会把当前窗口里已有的消息载入作为上下文，之后只判别**对方新发的**消息，
自己发的只记进上下文。切换聊天对象时上下文分开记。

## API 接口

调用层在 `chat_jev/jev.py`，只有一个方法：`JevClient.evaluate(state, questions) -> answers`。
默认走 **Vercel AI Gateway** 的 TypeSafe 兼容端点，三个环境变量决定后端：

| 变量 | Vercel（默认） | TypeSafe 直连 |
|---|---|---|
| `JEV_BACKEND` | `vercel` | `typesafe` |
| `JEV_BASE_URL` | `https://ai-gateway.vercel.sh/typesafe` | `https://api.typesafe.ai` |
| `JEV_MODEL` | `typesafe-ai/jev` | `jev-latest` |
| key | `AI_GATEWAY_API_KEY` | `TYPESAFE_API_KEY` |

设了 `JEV_BACKEND` 之后 `JEV_BASE_URL` / `JEV_MODEL` 有默认值，想指定别的地址再覆盖。
`JEV_BACKEND=vercel-native` 走 Vercel 原生 `/v1/evaluate`（问题类型 `boolean` 而不是 `noul`），客户端会自动转换，上层无感。

请求 / 响应形状（TypeSafe 格式）：

```jsonc
// POST {base_url}/v1/systemone
{ "model": "typesafe-ai/jev",
  "state": { "背景": "...", "历史消息": [...], "待判断消息": {...} },
  "questions": {
    "literal": { "type": "noul",   "instructions": "...", "criteria": { "true": "...", "false": "..." } },
    "intent":  { "type": "choice", "instructions": "...", "criteria": { "字面意思": "...", "反话赌气": "...", ... } } } }

// 200
{ "answers": { "literal": { "type": "noul", "noul": 0.44 },
               "intent":  { "type": "choice", "choice": "反话赌气", "probabilities": {...}, "confidence": 0.6 } } }
```

问题定义和 state 结构在 `chat_jev/judge.py`（`QUESTIONS` / `build_state`），要调判别口径改那里。

## 「接下来该怎么做」（可选，需要文本 LLM）

Jev 只能在**事先给定**的选项上分配概率，选项本身它想不出来。所以"下一步该做什么"用两段式：

1. **文本 LLM 发散**：拿到对话 + 判别结果，生成 3–5 个具体、互不相同的回应方案（`chat_jev/llm.py`）
2. **Jev 收敛**：把这些方案作为 `choice` 选项，问"作为我，接下来最应该采取哪个"，得到校准过的概率分布（`judge.rank_actions`）

在 `.env` 里填上 `LLM_API_KEY` 就自动开启，不用加参数（`--no-actions` 关掉）：

```bash
uv run chat-jev judge "没事，你忙吧" --ctx "我: 今晚加班"
# NO  表里一致  20%  → 反话赌气 80%  |  没事，你忙吧
#     → 建议：先哄一句再解释 62%  (承认没陪到她，再说加班的事)
#       其他：直接问她是不是不高兴 21%，先不回晚点打电话 17%

uv run chat-jev watch --app wechat      # 浮窗和菜单栏多一行"建议"
```

LLM 的接入留给你自己填，在 `.env`：

| 变量 | 说明 |
|---|---|
| `LLM_API_KEY` | 填了就启用，留空 = 不启用（启动时会提示一句） |
| `LLM_FLAVOR` | `anthropic`（默认，Anthropic Messages 格式，官方 SDK）或 `openai`（chat/completions） |
| `LLM_BASE_URL` | 见下表 |
| `LLM_MODEL` | 见下表 |

常见填法：

| provider | `LLM_FLAVOR` | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|---|
| Anthropic 直连 | anthropic | 留空 | `claude-opus-5` |
| Vercel AI Gateway | anthropic | `https://ai-gateway.vercel.sh` | `anthropic/claude-opus-5` |
| DeepSeek | anthropic | `https://api.deepseek.com/anthropic` | `deepseek-flash` |
| 只有 OpenAI 格式的 | openai | 填到 `/v1` 那一级 | 该 provider 的模型名 |

Claude 模型会保留自适应思考、用低 effort；其它模型走 Anthropic 兼容端点时会发 `thinking: disabled`（更快）。
换别的协议：在 `chat_jev/llm.py` 的 `LLMClient` 里加一个 `_complete_xxx` 方法。
LLM 这一步失败（没配 key、超时、返回格式不对）只会少一行"建议"，不影响 yes/no。

## 判别参数

| 变量 | 默认 | 说明 |
|---|---|---|
| `JEV_THRESHOLD` | `0.5` | 表里一致概率 ≥ 阈值算 YES。想更敏感就调高 |
| `JEV_RELATION` | `女朋友` | 对方和你的关系，写进背景 |
| `JEV_HISTORY` | `12` | 每次带多少条上下文 |

## 微信 OCR 布局

默认按 880×640 的默认窗口标定，单位 pt、相对窗口左上角：

| 变量 | 默认 | 含义 |
|---|---|---|
| `JEV_WECHAT_CHAT_LEFT` | 300 | 聊天区左边界（左边是会话列表） |
| `JEV_WECHAT_HEADER` | 60 | 顶部标题栏高度 |
| `JEV_WECHAT_FOOTER` | 170 | 底部输入区高度。拉高了输入框就调大，否则你正在打的字会被当消息 |
| `JEV_WECHAT_EDGE` | 110 | 气泡贴左/右边多少 pt 以内算对方/自己 |

判错了用 `snapshot --app wechat --boxes --save x.png` 看坐标再调。

## 局限

- 微信靠 OCR：字识别偶有错字（如 `llm`→`Im`），图片/表情/语音消息读不到；窗口要在屏幕上（可以被遮挡，不能最小化）。
- QQ 靠辅助功能：QQ 大版本更新改了 DOM class 就要跟着改 `QQAdapter`，用 `dump --app qq` 看新结构。
- 只判文字。同一条消息不重复判；撤回的消息不处理。
- 判断只是概率参考。别真拿它替你读心。

## 开发

```bash
uv run pytest
```

结构：

```
chat_jev/
  jev.py          Jev HTTP 客户端（可换后端）
  judge.py        state / questions 定义，answers → yes/no；rank_actions 给候选打分布
  llm.py          文本 LLM：提"下一步"候选（换 provider 改 LLMClient.complete）
  config.py       环境变量 / .env
  ax.py           辅助功能 API 封装
  capture.py      窗口截图 + Vision OCR
  sources/
    ax.py         AppSource：轮询 + diff；QQAdapter；GenericAdapter
    ocr.py        OCRAdapter（微信）
    clipboard.py  剪贴板来源
  overlay.py      浮窗
  menubar.py      菜单栏图标 + 菜单
  app.py          Watcher 主循环
  cli.py          命令行
```
