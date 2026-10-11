# 配置说明

配置写在 `config.json`：

- 源码运行时：项目目录下的 `config.json`（首次运行自动生成）。
- 打包版（exe）：`%APPDATA%\huayi\config.json`（若该目录不可写会退回系统临时目录）。

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
| `web_search` | 联网检索：`enabled` / `endpoint` / `api_key` / `max_results` |
| `keep_alive` | 本地模型常驻时间 |
| `max_text_len` | 选中文本超长截断阈值（字符） |
| `debounce_ms` | 连续划选防抖 |
| `hotkeys` | 热键（pynput 描述格式）：`translate` / `explain` / `input` |
| `prompts` | 译文 / 解释的系统提示词 |
| `prompts.chat` | 追问提示词；不配置时使用内置默认 |
| `blacklist_processes` | 进程名黑名单（如游戏、IDE） |
| `theme` | `dark` / `light` |
| `icon_timeout_s` | 浮标无操作自动隐藏秒数（默认 3） |
| `popup.width` / `popup.height` | 弹窗尺寸 |
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

## 联网检索

给「解释」和「追问」接入 [Ollama 托管搜索](https://docs.ollama.com/capabilities/web-search)：回答前先检索，再把结果作为上下文交给模型。**翻译标签不做检索**。

1. 到 [ollama.com/settings/keys](https://ollama.com/settings/keys) 建一个免费账号 API key；
2. 填进 `web_search.api_key`（或设环境变量 `OLLAMA_API_KEY`）；
3. 设 `web_search.enabled: true`，或运行时右键托盘 →「联网查询」。

> ⚠️ 检索会把**解释的原文**、**追问的本轮问题**发送到 `ollama.com`（与模型是否本地无关）。

## 严格离线

设 `"offline": true`：强制所有标签走本机 Ollama、仅允许连接回环地址，并关闭云端路由与联网检索。界面底部会显示「离线模式（仅本地）」。

该开关**不能**控制 Ollama 或系统剪贴板同步等其它程序的外部连接；要接近零外泄还需：

- 关闭 Ollama 云功能：设环境变量 `OLLAMA_NO_CLOUD=1` 后**重启 Ollama**（否则本机 `localhost` 仍可能把请求转交 Ollama 云端）。
- 关闭系统剪贴板历史与跨设备同步（热键取词会用到剪贴板兜底）。
- 用无敏感内容的文本自测四个标签，确认无外部连接。
