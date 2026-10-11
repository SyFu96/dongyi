# 划译 — 本地划词翻译

> A Windows text-selection translator powered by local Ollama or any OpenAI-compatible LLM.

桌面级划译工具（Windows），任意应用中拖选文字 → 选区旁浮出"译"图标 → 点击弹出译文/解释，还可以继续追问。

翻译引擎默认用本地 Ollama（可完全离线）；也可一键切换到任意 **OpenAI 兼容云端模型**（DeepSeek / Qwen / GLM / Kimi 等），
并给"解释/追问"开启 **联网检索**（Ollama 托管 web_search），补上模型知识截止之后的信息。

> ⚠️ **"本地模型"不等于"离线"**：联网检索会把**解释的原文 / 追问的本轮问题**发到 `ollama.com`；云端模型会把内容发给对应服务商。
> 想一键保证不外发：在 `config.json` 设 `"offline": true`——它强制全部走本机、禁用联网检索、并拒绝任何云端请求。
> 手动等价于：`provider: "ollama"`、`kind_providers` 全为 `ollama`（或留空）、`web_search.enabled: false`、`cloud.api_key` 为空，且 `base_url` 指向本机（`127.0.0.1` / `localhost`）——否则本机探测与模型请求仍可能连到远程 Ollama。

## 环境要求

- Windows 10/11
- Python 3.13+（用 [uv](https://docs.astral.sh/uv/) 管理环境，无需手动装 Python）
- Ollama（本地模式，模型 `qwen3-vl:30b-a3b-instruct` 或 `qwen3-vl-8b:latest`）
- 可选：云端模型 API key；可选：Ollama 账号 API key（联网检索用）

## 安装与运行

```powershell
# 1. 启动推理服务（多数机器上 Ollama 已作为服务常驻，可跳过）
ollama serve

# 2. 安装依赖（首次执行，会自动创建 .venv）
uv sync

# 3. 启动划译（日志写 app.log）
uv run python app.py
```

双击桌面的「划译」快捷方式会安静地在后台运行，不显示终端或启动页面。
首次启动自动预热模型（冷启动约 30s），托盘提示会显示模型状态。
右键托盘图标 →「状态与测试」可主动查看状态或测试翻译。
重复启动只保留已有后台实例。

桌面与开机自启动的入口使用 `launch.vbs` 隐藏启动窗口（源码运行）；打包成 exe 后入口直接指向 exe。更新入口并启用当前用户登录时自动启动：

```powershell
uv run python startup.py
```

右键托盘图标 →「开机自启动」可勾选/取消，无需管理员权限。
登录后如果本地 Ollama 尚未运行，工具会尝试在后台启动它，并等待服务就绪后预热模型。

## 使用

| 操作 | 说明 |
|---|---|
| 拖选文字 | 选区右下角浮出"译"图标，点击弹窗显示译文 |
| 双击/三击选词 | 同上 |
| `Ctrl+Alt+Shift+T` | 取焦点控件选区，直接弹"译文"（UIA 取不到时走剪贴板兜底） |
| `Ctrl+Alt+Shift+E` | 同上，直接弹"解释"标签 |
| 弹窗内切"解释"标签 | 对当前文本发起解释（首次切换才请求） |
|「显示在最前」| 保留结果窗口，点击其他应用和按 Esc 都不会关闭；点击 × 关闭 |
| 窗口顶部「拖动这里移动窗口」| 按住鼠标左键移动，各标签下均可拖动 |
| 窗口右下角缩放手柄 | 拖动调整宽度和高度，各标签共用；同一次运行中重新打开窗口保留调整后的大小 |
|「追问」标签 | 自动固定窗口；支持多行输入，Shift+Enter 或 Alt+Enter 换行，Enter 或「发送」提交，支持连续问答与失败重试 |
|「输入翻译」标签 | 弹窗第 4 个标签，自己输入内容翻译：`Ctrl+Alt+Shift+I`、托盘右键→「输入翻译…」或启动页按钮可直达；选目标语种（默认中↔英），`Ctrl+Enter` 或点「翻译」。翻译后该文本即成为当前讨论对象，可继续切到「解释/追问」 |
| 生成时的「停止」按钮 | 译文、解释、追问和输入翻译均可停止；保留已生成内容。停止追问后立即可以发送新问题，其余可重新生成 |
| `Esc` / 点击弹窗外 | 关闭未固定的弹窗，取消进行中的请求 |
| 托盘右键 | 状态与测试、输入翻译、设置、暂停/恢复监听、联网查询、开机自启动、打开配置文件、退出 |

弹窗出现时不抢焦点；点击追问后可以主动输入。问答结合当前原文、已有译文/解释及最近 12 轮对话；用哪个模型（本地/云端）由 `provider` 与 `kind_providers` 决定。
停止追问会保留本轮问题和部分回答，并在后续问答上下文中标记这轮回答尚未完成；停止不会清空窗口或卸载模型。
已有结果窗口（包括置顶或追问）打开时，新的拖选仍会出现「译」图标；出现图标不会覆盖原文或旧对话，只有点击新图标或使用热键才会切换到新原文，并清空旧对话。
默认热键额外加入 Shift，避开 Word 的 `Ctrl+Alt+T`（插入 ™）和 `Ctrl+Alt+E`（插入 €）；可在配置的 `hotkeys` 中自行更改。

## 模型与联网

### 图形化设置（推荐）

托盘右键 →「**设置…**」（或启动页「设置」按钮）打开设置窗口，无需手动改 JSON：

- **使用方式**：本地大模型（Ollama）/ 云端 API / 混合（翻译·输入本地、解释·追问云端）；
- **本地**：地址 + 模型下拉（「刷新模型」会列出本机已装模型，也可手输）；
- **云端**：地址 / 模型 / API Key，带「测试连接」；
- **联网检索**：启用开关 + Ollama API Key；
- **严格离线**：一键禁用联网检索与所有云端请求。

保存后，模型 / API / 联网 / 离线的改动**立即生效**（热键、弹窗尺寸等需重启）。

### 切换到云端模型（更聪明、更快）

默认走本地 Ollama（`provider: "ollama"`）。想换成更新、更强的模型，只需在 `config.json` 里：
把 `provider` 改为 `"openai"`，再填好 `cloud`：

```json
"provider": "openai",
"cloud": {
  "base_url": "https://api.deepseek.com/v1",   // 任意 OpenAI 兼容端点（含 /v1）
  "model": "deepseek-chat",
  "api_key": "sk-...",                          // 留空则读环境变量
  "api_key_env": "DEEPSEEK_API_KEY"             // 指定变量名；留空默认 OPENAI_API_KEY
}
```

`api_key` 为空时会读取 `api_key_env` 指定的环境变量（默认 `OPENAI_API_KEY`），便于不把密钥写进文件。

本地配置（`base_url`/`model`/`keep_alive`）会原样保留，把 `provider` 改回 `"ollama"` 即回到默认本地模式；
**注意这并不等于离线**——标签覆盖（`kind_providers`）和联网检索仍可能启用。要确保不外发请用 `offline` 开关。
云端模式不预热、不保活；密钥只留在本机配置文件里。

### 混合模式（推荐）：翻译本地、解释/追问云端

想让敏感原文只在本地翻译，又用云端模型做解释和追问，用 `kind_providers` 按标签分别指定：

```json
"provider": "openai",
"kind_providers": { "translate": "ollama", "input": "ollama", "explain": "openai", "chat": "openai" }
```

这样"译文"和"输入翻译"走本地 Ollama（快、离线），"解释/追问"走云端（更强、可联网）。
只要有一个标签走本地，启动时仍会探测并预热本地 Ollama；全云端时则跳过本地探测。

> 隐私提示：走云端的标签，其划选内容会发送给该服务商；**只把 `provider` 设为 `ollama` 并不能保证不外发**（标签覆盖与联网检索仍可能启用）。要确保敏感内容不外发，请用 `offline: true`。

### 严格离线（零外发）

在 `config.json` 里设 `"offline": true`，即可强制**所有标签走本机**、**禁用联网检索**，并**拒绝任何云端请求**（即使 `provider`/`kind_providers`/`web_search` 配了云端也一样）。此时界面底部会显示「离线模式（仅本地）」。

配套建议（真正零外泄还需要系统层配合）：

- 本地 Ollama 关闭云功能：设环境变量 `OLLAMA_NO_CLOUD=1`（否则本机 `localhost` 仍可能把请求转交 Ollama 云端）。
- 关闭系统剪贴板历史与跨设备同步（热键取词会用到剪贴板兜底）。
- 用无敏感内容的文本自测四个标签，确认无外部连接。
- 修改配置后要**退出托盘里的旧实例再重启**（配置仅在启动时加载）。

> 注：要"查询最新互联网信息"必然需要某种外部数据交换，无法与"严格零外泄"同时成立。

### 联网查询（解释 / 追问）

给"解释"和"追问"接入 [Ollama 托管搜索](https://docs.ollama.com/capabilities/web-search)，回答前先检索、再把结果作为上下文交给模型。
**翻译标签不做检索**（保证低延迟）——注意这不等于数据不出本机：若翻译路由到云端，原文仍会外发。启用方式：

1. 到 [ollama.com/settings/keys](https://ollama.com/settings/keys) 建一个免费账号 API key；
2. 在 `config.json` 的 `web_search.api_key` 填入（或设环境变量 `OLLAMA_API_KEY`）；
3. 把 `web_search.enabled` 设为 `true`，或运行时右键托盘 →「联网查询」勾选。

检索失败或没有 key 时会自动退回模型自身知识，不影响使用。检索在后台线程进行，状态栏会显示"联网检索中…"；此时点「停止」或关闭弹窗会作废这次检索。

> ⚠️ 检索会把**解释的原文**、**追问的本轮问题**发送到 `ollama.com`（与模型是否本地无关）。停用请关掉 `web_search.enabled`、托盘的「联网查询」，或直接开 `offline: true`。

## 已知限制（v1）

- 目标窗口为**管理员权限**时取词无效。
- 剪贴板兜底只还原文本格式（CF_UNICODETEXT），富格式（带排版的 Excel/Word 单元格）丢失。
- 传统控制台（`cmd` 窗口）不支持兜底（Ctrl+C 是中断信号）；Windows Terminal 可以。
- 键盘选区（Shift+方向键）不浮图标，需用热键。
- 部分 Electron/Java 应用 UIA 取词延迟较高或取不到（JetBrains 需热键兜底）；浏览器首次查询慢几百 ms 属正常。

## 配置（config.json）

首次运行自动生成；仓库只提供无密钥模板 `config.example.json`，`config.json` 已被 `.gitignore` 忽略（避免密钥入库）。
源码运行时配置在项目目录；**打包成 exe 后**配置与日志写到 `%APPDATA%\huayi\`（若不可写会退回系统临时目录）。
手工编辑配置文件后需**重启**才生效；用「设置」窗口保存的改动（模型/API/联网/离线）立即生效。
主要字段：

| 字段 | 含义 |
|---|---|
| `provider` | `ollama`（本地，默认）/ `openai`（云端 OpenAI 兼容） |
| `kind_providers` | 按标签覆盖 provider，如 `{"translate": "ollama"}` 实现混合模式 |
| `offline` | 默认 `false`；`true` = 严格离线（强制全本地、禁检索、拒绝云端请求） |
| `base_url` | 本地 Ollama 地址，默认 `http://localhost:11434` |
| `model` | 本地模型名；换 `qwen3-vl-8b:latest` 更小更快 |
| `cloud` | 云端后端：`base_url` / `model` / `api_key`（`provider="openai"` 时生效） |
| `web_search` | 联网检索：`enabled` / `endpoint` / `api_key` / `max_results` |
| `keep_alive` | 模型常驻时间 |
| `max_text_len` | 选中文本超长截断阈值（字符） |
| `debounce_ms` | 连续划选防抖 |
| `hotkeys` | 热键（pynput 描述格式） |
| `prompts` | 译文/解释的系统提示词 |
| `blacklist_processes` | 进程名黑名单（如游戏、IDE） |
| `theme` | `dark` / `light` |
| `popup.width/height` | 弹窗尺寸 |
| `show_startup_window` | 默认 `false`，启动时不弹页面 |
| `auto_start_ollama` | 默认 `true`，本机默认地址的服务未启动时尝试后台启动 |
| `prompts.chat` | 追问提示词；不配置时使用内置阅读助手提示词 |

## 测试

```powershell
# LLM 链路：流式翻译 + 解释，打印首字延迟/总耗时
uv run python test_llm.py

# 取词链：3 秒倒计时后去别的窗口选中文字，打印 text/rect/source
# 运行中输入 e 可加测 explicit（剪贴板兜底，会短暂占用并还原剪贴板）
uv run python test_capture.py

# 启动、置顶、追问、取消请求的自动回归检查
uv run python -m unittest test_startup test_features test_interaction -v

# 真实模型和窗口：翻译 + 连续追问 + 中途停止解释/回答 + 放大阅读
uv run python test_live.py

# 真实静默启动/自启动入口/重复启动（验证后保持后台运行）
uv run python test_silent_launch.py
```

端到端验收 10 个用例见《开发执行文档》§7.2。

## 排错

| 现象 | 处置 |
|---|---|
| 弹窗报"无法连接 Ollama" | 确认 `ollama serve` 在运行，或 base_url 正确 |
| 弹窗报"模型不存在" | `ollama pull <模型名>` |
| 弹窗报"云端鉴权失败" | 检查 `cloud.api_key` 是否正确、是否过期 |
| 弹窗报"云端模型不存在" | 检查 `cloud.base_url`（记得带 `/v1`）与 `cloud.model` 拼写 |
| 勾选"联网查询"立刻弹回 | 未配置 `web_search.api_key` 或环境变量 `OLLAMA_API_KEY`；填好后重启 |
| 解释没走联网 | 确认 `web_search.enabled=true` 且已配 key；译文标签本就不联网 |
| 译文有思考过程输出 | 不应出现；代码已强制 `think:false` |
| 觉得翻译慢 | 看 app.log 中预热是否完成；换 8B 模型，或改用云端模型 |

## v1 明确不做（v2 备忘）

OCR 截图翻译（qwen3-vl 自带视觉能力，只需把截图放 `images` 字段）、管理员窗口支持。
正式版技术栈（Tauri 2 / WPF）待原型验证后再评估；capture.py 的取词逻辑可直接翻译到目标栈。
打包见上文「打包为 Windows 程序」。

## 打包为 Windows 程序（可选）

```powershell
uv sync
uv run pyinstaller --noconfirm huayi.spec
```

产出 `dist/huayi/`（**onedir 目录包**），运行其中的 `huayi.exe` 即可。首次运行后配置与日志写入 `%APPDATA%\huayi\`。
本地翻译仍需用户自行安装 Ollama；模型权重不随包分发。

> 分发二进制前请阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)：PySide6 / pynput 为 LGPLv3，打包分发时需随包提供相应许可文本与源码/替换方式。

## 许可

本项目采用 **GNU General Public License v3.0（GPL-3.0-only）**，全文见 [`LICENSE`](LICENSE)。
第三方依赖（PySide6、pynput 等）的许可与分发注意事项见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
