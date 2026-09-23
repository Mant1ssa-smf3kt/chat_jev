# chat-jev

盯着桌面 QQ 的聊天窗口，对方每发来一句话，就用 [Jev](https://typesafe.ai)（TypeSafe AI 的判别模型）判断：
**她想表达的意思是不是这句话的字面意思？** 表里一致 → `YES`，话里有话 → `NO`，顺带给出最可能的真实意图。

结果显示在屏幕右上角的浮窗里；错过的旧消息，**按住 ⌥ 点一下**就在气泡旁边判。程序不进 Dock，靠**菜单栏图标**（💬 气泡）确认它在跑：
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
| 任何应用 | 剪贴板：复制一句话就判别 | 无 |

判别只把**文字**发给 Jev（最近 12 条上下文 + 待判断的这条）。

> 微信已放弃：4.x 是自绘界面，辅助功能树是空的，截图 OCR 又太不稳定。微信里的话可以用剪贴板来源判。

## 安装（app，推荐）

1. 到 [Releases](https://github.com/Mant1ssa-smf3kt/chat_jev/releases) 下载 `chat-jev-<版本>-macos-arm64.zip`，解压，把 `chat-jev.app` 拖进「应用程序」。
   目前只有 Apple 芯片版，需要 macOS 14+。
2. app 没有经过 Apple 公证，第一次打开会被拦下。任选一种放行：
   - 双击被拦后，到 系统设置 → 隐私与安全性，页面底部点「仍要打开」
   - 或者在终端执行一次 `xattr -dr com.apple.quarantine /Applications/chat-jev.app`
3. 第一次打开会生成配置文件并提示你填密钥：
   `~/Library/Application Support/chat-jev/.env`，填上 `AI_GATEWAY_API_KEY`（或 `TYPESAFE_API_KEY`），保存后再打开 chat-jev。
   其它设置和下文的环境变量同名，都写在这个文件里。**app 读不到 shell 里 export 的变量**，只认这个文件。
4. 系统会请求「辅助功能」权限：系统设置 → 隐私与安全性 → 辅助功能，打开 **chat-jev**。
   授权后不用重启，浮窗会提示「已获得权限」。

之后打开 QQ 的聊天窗口就行。菜单栏图标里可以暂停、打开配置文件、打开日志（`~/Library/Logs/chat-jev.log`）、退出。

想改 app 的默认行为，在配置文件里加一行，写法和命令行参数一样：

```bash
JEV_WATCH_ARGS="--pick-only --interval 0.5"     # 只判点选的消息、读得勤一些
```

### 权限只给 chat-jev，不给终端

app 是独立的程序，辅助功能权限记在 chat-jev 名下。**终端不需要任何权限**，
以前给 Terminal / iTerm / Ghostty 开过的可以关掉：系统设置 → 隐私与安全性 → 辅助功能，把终端的开关关掉或用「−」删掉。
（整项清空可以用 `tccutil reset Accessibility <终端的 bundle id>`，比如 Ghostty 是 `com.mitchellh.ghostty`。）

chat-jev 只要「辅助功能」这一项：读 QQ 窗口的消息列表，以及看 ⌥+点击点在哪条消息上。
它不需要屏幕录制、输入监控、完全磁盘访问。

**更新版本后要重新授权**：app 用的是 ad-hoc 签名，系统按签名记权限，新版本对系统来说是另一个程序。
在辅助功能列表里把旧的 chat-jev 用「−」删掉，再打开新版，按提示重新开一次。

## 从源码运行（开发）

```bash
cd chat_jev
uv sync
cp .env.example .env    # 填 AI_GATEWAY_API_KEY（或 TYPESAFE_API_KEY）
```

需要 macOS 14+、Python 3.13、[uv](https://docs.astral.sh/uv/)。

注意：从终端跑 `watch` / `snapshot` / `dump` 时，系统把辅助功能权限算在**终端**头上，
得给终端授权才能读到 QQ。只想让 chat-jev 拿权限，就用 app；`judge` 单句判别不需要任何权限。

## 命令行用法

app 做的就是 `watch --app qq`。下面这些是从源码跑的命令：

```bash
# 单句判别（带上下文）
uv run chat-jev judge "没事，你忙吧" --ctx "我: 今晚加班，不能陪你吃饭了"

# 实时监听 QQ（浮窗）
uv run chat-jev watch --app qq

# 实时监听 QQ，只看某个人
uv run chat-jev watch --app qq --contact 她的昵称

# 不自动判新消息，只判 ⌥+点击选中的
uv run chat-jev watch --pick-only

# 不要浮窗，只打终端
uv run chat-jev watch --app qq --no-overlay

# 复制即判别（任何应用都行）
uv run chat-jev watch --source clipboard

# 调试：看看现在解析出了什么
uv run chat-jev snapshot --app qq --frames
uv run chat-jev dump --app qq | less
```

`watch` 启动时浮窗会弹一下"chat-jev 已启动"，菜单栏出现气泡图标。它会把当前窗口里已有的消息载入作为上下文，之后只判别**对方新发的**消息，
自己发的只记进上下文。切换聊天对象时上下文分开记。

### ⌥+点击：判任意一条消息

错过了、或者是启动之前的消息：在 QQ 里翻回去，**按住 Option 点一下那条消息**，
结果就显示在那个气泡旁边。上下文用它**前面**的消息，不带后面的（包括你往上翻时经过的，见下方「局限」）。

- 点同一条消息第二次，直接显示上次的结果，不重复请求
- 点到自己的消息、图片或表情，会提示判不了
- 只是旁听点击，不拦截：点击照常送到 QQ
- 连着点了好几条时，浮窗只显示最后点的那条，前面几条的结果照样打印在终端
- 要浮窗模式才能用（`--no-overlay` 下没有），`--no-pick` 关掉
- 点了没反应：用 `snapshot --frames` 看每条消息的屏幕坐标对不对

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

uv run chat-jev watch --app qq          # 浮窗和菜单栏多一行"建议"
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

## 局限

- QQ 靠辅助功能：QQ 大版本更新改了 DOM class 就要跟着改 `QQAdapter`，用 `dump --app qq` 看新结构。
- 只判文字。自动模式下同一条消息不重复判；撤回的消息不处理。
- QQ 的消息列表是虚拟滚动，一次只渲染十几条（`snapshot` 也只能看到这些）。`watch` 运行期间会把每次读到的
  片段拼成完整记录，所以**往上翻过的消息都会留作上下文**；但启动后没翻到过的更早消息拿不到。
  翻得太快、两次读取之间没有重叠时，记录会从当前这段重新开始，可以用 `--interval 0.5` 读得更勤一些。
- 判断只是概率参考。别真拿它替你读心。

## 开发

```bash
uv run pytest
packaging/build.sh      # 打包：dist/chat-jev.app 和 dist/chat-jev-<版本>-macos-<架构>.zip
```

版本号在 `pyproject.toml`。打包用 PyInstaller（配置在 `packaging/chat-jev.spec`），
脚本最后会用 `CHAT_JEV_SELFTEST=1` 跑一遍打出来的 app，确认模块都在、不弹权限框。

结构：

```
chat_jev/
  jev.py          Jev HTTP 客户端（可换后端）
  judge.py        state / questions 定义，answers → yes/no；rank_actions 给候选打分布
  llm.py          文本 LLM：提"下一步"候选（换 provider 改 LLMClient.complete）
  config.py       环境变量 / .env
  ax.py           辅助功能 API 封装
  sources/
    ax.py         AppSource：轮询 + diff；QQAdapter；GenericAdapter
    clipboard.py  剪贴板来源
  overlay.py      浮窗
  picker.py       ⌥+点击的全局鼠标监听
  bundle.py       app 入口：日志、配置文件、缺密钥提示
  menubar.py      菜单栏图标 + 菜单
  app.py          Watcher 主循环
  cli.py          命令行
```
