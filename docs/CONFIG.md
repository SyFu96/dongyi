# 配置说明

配置写在 `config.json`：

- 源码运行时：项目目录下的 `config.json`（首次运行自动生成）。
- 打包版（exe）：`%APPDATA%\dongyi\config.json`（若该目录不可写会退回系统临时目录）。
- 从旧版（划译 huayi）升级：首次启动会自动把整个 `%APPDATA%\huayi\` 数据目录迁移为 `%APPDATA%\dongyi\`，配置、术语表、知识库索引与翻译记忆全部保留。

> 用「设置…」窗口保存的改动（模型 / API / 联网 / 离线）**立即生效**；手工编辑文件后需**重启**。

仓库只提供无密钥模板 [`config.example.json`](../config.example.json)，`config.json` 已被 `.gitignore` 忽略，避免密钥入库。

## 字段

| 字段 | 含义 |
|---|---|
| `provider` | `ollama`（本地，默认）/ `openai`（云端 OpenAI 兼容） |
| `kind_providers` | 按标签覆盖 provider，如 `{"translate": "ollama"}` 实现混合模式 |
| `offline` | 默认 `false`；`true` = 严格离线（强制全本地、禁检索、拒绝云端请求） |
| `base_url` | 本地 Ollama 地址，默认 `http://localhost:11434` |
| `model` | 本地模型名；想更小更快可用 `qwen3-vl:8b-instruct` |
| `cloud` | 云端后端：`base_url` / `model` / `api_key` / `api_key_env` |
| `web_search` | 联网检索：`enabled` / `endpoint` / `api_key` / `max_results`；Rust 版另支持下述 `kinds` 功能开关 |
| `web_search.kinds` | Rust 版独立搜索开关：`explain`、`chat` 默认 `true`，`input` 默认 `false`；仍受总开关、搜索 key 和严格离线限制 |
| `keep_alive` | 本地模型常驻时间 |
| `max_text_len` | 选中文本超长截断阈值（字符） |
| `debounce_ms` | 连续划选防抖 |
| `hotkeys` | 热键（pynput 描述格式）：`translate` / `explain` / `input` |
| `prompts` | 译文 / 解释的系统提示词 |
| `prompts.chat` | 追问提示词；不配置时使用内置默认 |
| `domains` | 领域（学科）配置：id → `{name, note, enabled, glossary_file, kb_dirs, kb_enabled, kb_for_translate}`，详见 [DOMAINS.md](DOMAINS.md) |
| `active_domain` | 当前激活领域 id；空 = 通用模式。弹窗/托盘切换后自动写回 |
| `tm_enabled` | 翻译记忆总开关，默认 `true` |
| `blacklist_processes` | 进程名黑名单（如游戏、IDE） |
| `theme` | `dark` / `light` / `system`（跟随系统）；设置 → 外观选择后立即预览，保存记住选择，取消恢复原主题 |
| `icon_timeout_s` | 浮标无操作自动隐藏秒数（默认 3） |
| `clipboard_fallback` | 拖选（划词）路径 UIA 取词失败后的自动剪贴板兜底总开关，默认 `true`。热键路径不在此开关限制内（始终可用兜底） |
| `clipboard_fallback_processes` | 自动兜底允许发键的阅读器进程白名单，默认 `["sioyek.exe"]`。白名单外的应用划选仍走 UIA 或热键；终端窗口与 `blacklist_processes` 永不自动发键 |
| `popup.width` / `popup.height` | 弹窗初始尺寸（默认 460×420，最小 420×420） |
| `show_startup_window` | 默认 `false`，启动时不弹页面 |
| `auto_start_ollama` | 默认 `true`，本机默认地址的服务未启动时尝试后台启动 |

## 模型：本地 / 云端 / 混合

### 本地（默认）

`provider: "ollama"` 默认连接本机 Ollama；实际请求还受 `base_url`、标签覆盖和联网检索设置影响。
离线使用请按下文「严格离线」配置，并关闭 Ollama 云功能。

### 云端（任意 OpenAI 兼容）

```json
"provider": "openai",
"cloud": {
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "api_key": "sk-...",
  "api_key_env": "DEEPSEEK_API_KEY"
}
```

`api_key` 留空时会读取 `api_key_env` 指定的环境变量（默认 `OPENAI_API_KEY`），便于不把密钥写进文件。
在「设置…」里填写的 API Key 会以**明文**保存在 `config.json`；介意的话请用环境变量方式。

> ⚠️ 只把 `provider` 改回 `"ollama"` **不等于离线**——标签覆盖和联网检索仍可能启用。

### 混合（推荐）

翻译/输入走本地、解释/追问走云端：

```json
"provider": "openai",
"kind_providers": { "translate": "ollama", "input": "ollama", "explain": "openai", "chat": "openai" }
```

## 划词兜底（拖选路径的剪贴板取词）

sioyek 等自绘阅读器不支持 UIA TextPattern，拖选取词拿不到选区：此时若该
进程在 `clipboard_fallback_processes` 白名单且 `clipboard_fallback` 开启，
会自动模拟一次 Ctrl+C 读取选区，然后把你的剪贴板恢复原状（含空剪贴板）。

- 自动兜底前会核对请求时效与前台窗口身份：连拖多次、拖动窗口/滚动条
  （前台已切换）时直接放弃，不会向无关窗口发键。
- 只在剪贴板当前为空或纯文本（含系统合成格式）时操作：原图/文件/富格式
  内容直接跳过，只留热键路径可用。
- 其他阅读器想启用：把进程名加进白名单即可，例如：

```json
"clipboard_fallback": true,
"clipboard_fallback_processes": ["sioyek.exe", "sumatrapdf.exe"]
```

- 热键路径不受白名单限制（用户显式触发）；热键兜底对含纯文本的剪贴板
  会还原备份文本，但富格式（带排版的 Excel/Word 单元格）只还原其中的
  纯文本部分——这是显式操作下保留旧行为的已知取舍。

## 联网检索

给「解释」和「追问」接入 [Ollama 托管搜索](https://docs.ollama.com/capabilities/web-search)：回答前先检索，再把结果作为上下文交给模型。Rust 版的「输入翻译」也可单独开启搜索，默认关闭；划词「译文」不做联网检索。个人知识库的本地检索可单独开启，见 [DOMAINS.md](DOMAINS.md)。

1. 到 [ollama.com/settings/keys](https://ollama.com/settings/keys) 建一个免费账号 API key；
2. 填进 `web_search.api_key`（或设环境变量 `OLLAMA_API_KEY`）；
3. 设 `web_search.enabled: true`，或运行时右键托盘 →「联网查询」。

Rust 版在「设置 → 模型」分别选择追问和输入翻译的本地/云端模型，在「设置 → 联网搜索」控制各功能是否搜索。弹窗的「本地 / 云端」按钮只切换模型；本地模型也可配合搜索，无需云端模型 key，搜索仍使用独立的 Ollama 搜索 key。

```json
"kind_providers": { "chat": "ollama", "input": "ollama" },
"web_search": {
  "enabled": true,
  "kinds": { "explain": true, "chat": true, "input": false },
  "api_key": "",
  "endpoint": "https://ollama.com/api/web_search",
  "max_results": 5
}
```

> ⚠️ 检索会把**解释的原文**、**追问的本轮问题**，以及主动开启输入翻译搜索后的**输入文本**发送到 `ollama.com`（与模型是否本地无关）。

## 严格离线

设 `"offline": true`：强制所有标签走本机 Ollama、仅允许连接回环地址，并关闭云端路由与联网检索。界面底部会显示「离线模式（仅本地）」。

该开关**不能**控制 Ollama 或系统剪贴板同步等其它程序的外部连接；要接近零外泄还需：

- 关闭 Ollama 云功能：设环境变量 `OLLAMA_NO_CLOUD=1` 后**重启 Ollama**（否则本机 `localhost` 仍可能把请求转交 Ollama 云端）。
- 关闭系统剪贴板历史与跨设备同步（热键取词会用到剪贴板兜底）。
- 用无敏感内容的文本自测四个标签，确认无外部连接。
