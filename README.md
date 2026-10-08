# 划译 — 本地划词翻译

桌面级划译工具（Windows），任意应用中拖选文字 → 选区旁浮出"译"图标 → 点击弹出译文/解释，还可以继续追问。
翻译引擎为本地 Ollama，全程离线可用。

## 环境要求

- Windows 10/11
- Python 3.13+（用 [uv](https://docs.astral.sh/uv/) 管理环境，无需手动装 Python）
- Ollama（模型 `qwen3-vl:30b-a3b-instruct` 或 `qwen3-vl-8b:latest`）

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

桌面与开机自启动的入口使用 `launch.vbs` 隐藏启动窗口。更新入口并启用当前用户登录时自动启动：

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
| 窗口顶部「拖动这里移动窗口」| 按住鼠标左键移动，译文/解释/追问标签下均可拖动 |
| 窗口右下角缩放手柄 | 拖动调整宽度和高度，三个标签共用；同一次运行中重新打开窗口保留调整后的大小 |
|「追问」标签 | 自动固定窗口；输入问题后按 Enter 或点击「发送」，支持连续问答与失败重试 |
| 生成时的「停止」按钮 | 译文、解释和追问均可停止；保留已生成内容。停止追问后立即可以发送新问题，停止译文/解释后可重新生成 |
| `Esc` / 点击弹窗外 | 关闭未固定的弹窗，取消进行中的请求 |
| 托盘右键 | 状态与测试、暂停/恢复监听、开机自启动、打开配置文件、退出 |

弹窗出现时不抢焦点；点击追问后可以主动输入。问答结合当前原文、已有译文/解释及最近 12 轮对话，均由本地 Ollama 处理。
停止追问会保留本轮问题和部分回答，并在后续问答上下文中标记这轮回答尚未完成；停止不会清空窗口或卸载模型。
已有结果窗口（包括置顶或追问）打开时，新的拖选仍会出现「译」图标；出现图标不会覆盖原文或旧对话，只有点击新图标或使用热键才会切换到新原文，并清空旧对话。
默认热键额外加入 Shift，避开 Word 的 `Ctrl+Alt+T`（插入 ™）和 `Ctrl+Alt+E`（插入 €）；可在配置的 `hotkeys` 中自行更改。

## 已知限制（v1）

- 目标窗口为**管理员权限**时取词无效。
- 剪贴板兜底只还原文本格式（CF_UNICODETEXT），富格式（带排版的 Excel/Word 单元格）丢失。
- 传统控制台（`cmd` 窗口）不支持兜底（Ctrl+C 是中断信号）；Windows Terminal 可以。
- 键盘选区（Shift+方向键）不浮图标，需用热键。
- 部分 Electron/Java 应用 UIA 取词延迟较高或取不到（JetBrains 需热键兜底）；浏览器首次查询慢几百 ms 属正常。

## 配置（config.json）

首次运行自动生成。主要字段：

| 字段 | 含义 |
|---|---|
| `base_url` | Ollama 地址，默认 `http://localhost:11434` |
| `model` | 模型名；换 `qwen3-vl-8b:latest` 更小更快 |
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
| 译文有思考过程输出 | 不应出现；代码已强制 `think:false` |
| 觉得翻译慢 | 看 app.log 中预热是否完成；或换 8B 模型 |

## v1 明确不做（v2 备忘）

OCR 截图翻译（qwen3-vl 自带视觉能力，只需把截图放 `images` 字段）、打包 exe、管理员窗口支持。
正式版技术栈（Tauri 2 / WPF）待原型验证后再评估；capture.py 的取词逻辑可直接翻译到目标栈。
