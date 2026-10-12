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
| `app.py` | 入口与主编排：加载配置 → 探测/预热 → 监听 → Qt 循环；`_compose_system` 统一组装领域提示词 |
| `capture.py` | 取词：UIA 读选中文本 + 受控的剪贴板兜底（拖选按白名单自动、热键始终可用） |
| `trigger.py` | 划词/双击检测、全局热键、浮标窗 |
| `llm.py` | 双后端流式客户端（本地 Ollama / OpenAI 兼容云端），按标签路由 |
| `search.py` | 联网检索客户端（Ollama 托管 `web_search`，可中断） |
| `domains.py` | 领域配置解析、术语表 CSV 加载/命中匹配/注入格式化 |
| `knowledge.py` | 个人知识库：文档解析(txt/md/csv/json/pdf/docx)、分块、BM25 索引与检索 |
| `tm.py` | 翻译记忆：句对存储、相似度检索、参考译例注入 |
| `netutil.py` | 不跟随重定向的 URL 打开（本机探测/刷新用） |
| `conversation.py` | 追问上下文组装（含领域上下文注入） |
| `popup.py` | 弹窗（译文/解释/追问/输入翻译 四标签）、托盘、浮标、Toast、记忆编辑对话框 |
| `settings.py` | 图形化设置窗口（模型/联网/领域与知识库管理） |
| `theme.py` | 深浅主题的配色与控件样式 |
| `instance.py` | 单实例（命名互斥量 + 本地套接字） |
| `startup.py` | 开机自启动快捷方式（源码用 `launch.vbs`，exe 指向自身） |

数据文件（与 `config.json` 同目录）：`glossaries/<领域id>.csv` 术语表、`kb_index/` 知识库索引、`tm/<领域id>.jsonl` 翻译记忆。

界面预览：`uv run python tools/preview_ui.py` 使用示例数据生成深浅主题的四标签与设置页 PNG，写入 `docs/screenshots/ui-refresh/`；不读取个人配置或连接模型。

## 测试

```powershell
# 启动、置顶、追问、取消请求与领域适配的自动回归（CI 也跑这七组）
uv run python -m unittest test_startup test_features test_interaction test_domains test_knowledge test_tm test_domain_integration test_theme test_settings_launch -v

# LLM 链路：流式翻译 + 解释，打印首字延迟/总耗时
uv run python test_llm.py

# 取词链：3 秒倒计时后去别的窗口选中文字，打印 text/rect/source
uv run python test_capture.py

# 真实模型和窗口：翻译 + 连续追问 + 中途停止 + 放大阅读
uv run python test_live.py

# 真实静默启动/自启动入口/重复启动
uv run python test_silent_launch.py
```

`test_settings_launch` 使用原生 Windows 子进程模拟 `SW_HIDE` 启动，检查设置/状态窗首次打开、隐藏后重开和最小化后恢复时的实际可见性。

CI（GitHub Actions）在 `windows-latest` 上以 `QT_QPA_PLATFORM=offscreen` 跑 `test_startup test_features test_interaction`。

## 打包

```powershell
uv sync
uv run pyinstaller --noconfirm dongyi.spec
```

产出 `dist/dongyi/`（**onedir** 目录包），运行其中的 `dongyi.exe`。打包版配置与日志写入 `%APPDATA%\dongyi\`。

发布二进制前请阅读 [`release/`](../release)（许可、对应源码、重建/替换说明）与 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)：
PySide6 / pynput 为 LGPLv3，分发二进制时需随包提供相应许可文本与源码/替换方式。
