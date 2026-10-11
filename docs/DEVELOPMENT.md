# 开发

## 环境

```powershell
uv sync                 # 创建 .venv 并装依赖
uv run python app.py    # 启动（日志写 app.log）
```

需要 Windows、Python 3.13+（由 [uv](https://docs.astral.sh/uv/) 管理）。

## 项目结构

| 文件 | 职责 |
|---|---|
| `app.py` | 入口与主编排：加载配置 → 探测/预热 → 监听 → Qt 循环 |
| `capture.py` | 取词：UIA 读选中文本 + 热键路径的剪贴板兜底 |
| `trigger.py` | 划词/双击检测、全局热键、浮标窗 |
| `llm.py` | 双后端流式客户端（本地 Ollama / OpenAI 兼容云端），按标签路由 |
| `search.py` | 联网检索客户端（Ollama 托管 `web_search`，可中断） |
| `netutil.py` | 不跟随重定向的 URL 打开（本机探测/刷新用） |
| `conversation.py` | 追问上下文组装 |
| `popup.py` | 弹窗（译文/解释/追问/输入翻译 四标签）、托盘、浮标、Toast |
| `settings.py` | 图形化设置窗口 |
| `instance.py` | 单实例（命名互斥量 + 本地套接字） |
| `startup.py` | 开机自启动快捷方式（源码用 `launch.vbs`，exe 指向自身） |

## 测试

```powershell
# 启动、置顶、追问、取消请求的自动回归（CI 也跑这三组）
uv run python -m unittest test_startup test_features test_interaction -v

# LLM 链路：流式翻译 + 解释，打印首字延迟/总耗时
uv run python test_llm.py

# 取词链：3 秒倒计时后去别的窗口选中文字，打印 text/rect/source
uv run python test_capture.py

# 真实模型和窗口：翻译 + 连续追问 + 中途停止 + 放大阅读
uv run python test_live.py

# 真实静默启动/自启动入口/重复启动
uv run python test_silent_launch.py
```

CI（GitHub Actions）在 `windows-latest` 上以 `QT_QPA_PLATFORM=offscreen` 跑 `test_startup test_features test_interaction`。

## 打包

```powershell
uv sync
uv run pyinstaller --noconfirm huayi.spec
```

产出 `dist/huayi/`（**onedir** 目录包），运行其中的 `huayi.exe`。打包版配置与日志写入 `%APPDATA%\huayi\`。

发布二进制前请阅读 [`release/`](../release)（许可、对应源码、重建/替换说明）与 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)：
PySide6 / pynput 为 LGPLv3，分发二进制时需随包提供相应许可文本与源码/替换方式。
