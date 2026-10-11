<div align="center">

# 划译 · huayi

**Windows 划词翻译工具，支持本地和云端模型。**

![License](https://img.shields.io/badge/license-GPL--3.0--only-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4)
![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenAI%20compatible-000)

</div>

在支持取词的应用中选中文字，点击选区旁的「译」，即可查看译文；还可以解释术语、继续追问。

> 使用云端模型时，当前文本会发送给对应服务商；云端追问还会携带原文、已有译文或解释及最近对话。
> 联网检索默认向 Ollama 搜索服务发送**解释的原文或本轮问题**。需要离线使用时，请按
> [配置说明](docs/CONFIG.md)启用「严格离线」，并关闭 Ollama 云功能。

## 功能

- **划词翻译**：选中文字后点击「译」，在弹窗中查看结果。
- **解释与追问**：解释当前文本，并围绕它继续提问。
- **输入翻译**：自己输入文本，选择目标语种翻译。
- **本地模型**：可连接本机 [Ollama](https://ollama.com/)；离线使用条件见[配置说明](docs/CONFIG.md)。
- **云端模型**：可接入支持流式 Chat Completions 的 OpenAI 兼容服务（DeepSeek、Qwen、GLM、Kimi 等）。
- **联网检索**：解释和追问可参考搜索结果；检索失败时使用模型自身知识。
- **领域适配**：按学科切换提示词与强制术语表；可指向个人文献文件夹做知识库检索（RAG），确认过的译文自动积累为翻译记忆，详见 [docs/DOMAINS.md](docs/DOMAINS.md)。

## 快速开始

### 直接下载（推荐）

到 [**Releases**](https://github.com/SyFu96/huayi/releases) 下载 `huayi-v0.1.0-windows-x64.zip`，**完整解压**后双击 `huayi.exe`。打包版无需安装 Python；当前为公开测试版。

- 本地翻译：先装 [Ollama](https://ollama.com/)，再拉一个模型：

  ```powershell
  ollama pull qwen3-vl:8b-instruct          # 较小、较快
  # 或 ollama pull qwen3-vl:30b-a3b-instruct # 30B 版本，模型文件约 20GB；效果与速度取决于文本和硬件
  ```

  然后在「设置…」里把模型名改成对应名称。

- 云端翻译：托盘右键 →「设置…」，选「云端 API」，填地址 / 模型 / API Key。

### 从源码运行

需要 Windows、Git 和 [uv](https://docs.astral.sh/uv/)（自动管理 Python 3.13+）：

```powershell
git clone https://github.com/SyFu96/huayi.git
cd huayi
uv sync
uv run python app.py
```

## 怎么用

| 操作 | 说明 |
|---|---|
| 拖选文字 / 双击选词 | 选区旁浮出「译」，点它出译文 |
| `Ctrl+Alt+Shift+T` / `E` | 不拖选也能取当前选中文字，直接出「译文」/「解释」 |
| `Ctrl+Alt+Shift+I` | 呼出「输入翻译」，自己打字翻译 |
| 弹窗里的「解释」「追问」「输入翻译」 | 同一窗口里的另外三个标签 |
| 托盘右键 | 设置、暂停监听、联网查询、开机自启动、退出 |

程序启动后安静地在后台运行（托盘图标）。改模型、填 API、开联网或严格离线，都在**托盘右键 →「设置…」**里。
更多操作（固定窗口、停止生成、追问换行、输入翻译快捷键等）见 [docs/USAGE.md](docs/USAGE.md)。

## 配置

首次运行自动生成 `config.json`（打包版写在 `%APPDATA%\huayi\`）。字段说明见
[`config.example.json`](config.example.json) 和 [docs/CONFIG.md](docs/CONFIG.md)。

## 文档

- 详细用法 → [docs/USAGE.md](docs/USAGE.md)
- 配置字段与模型 / 联网 / 离线 → [docs/CONFIG.md](docs/CONFIG.md)
- 领域适配与个人知识库 → [docs/DOMAINS.md](docs/DOMAINS.md)
- 排错与已知限制 → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- 开发、测试、打包 → [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## 许可

[GPL-3.0-only](LICENSE)。第三方组件许可与分发注意事项见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
