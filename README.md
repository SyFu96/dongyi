# 划译 — 本地划词翻译

桌面级划译工具（Windows），任意应用中拖选文字 → 选区旁浮出"译"图标 → 点击弹出译文/解释。
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

# 3. 启动划译（无控制台窗口，日志写 app.log）
.venv\Scripts\pythonw.exe app.py
```

首次启动后台自动预热模型（冷启动最长约 30s），之后就绪。托盘图标可见。

## 使用

| 操作 | 说明 |
|---|---|
| 拖选文字 | 选区右下角浮出"译"图标，点击弹窗显示译文 |
| 双击/三击选词 | 同上 |
| `Ctrl+Alt+T` | 取焦点控件选区，直接弹"译文"（UIA 取不到时走剪贴板兜底） |
| `Ctrl+Alt+E` | 同上，直接弹"解释"标签 |
| 弹窗内切"解释"标签 | 对当前文本发起解释（首次切换才请求） |
| `Esc` / 点击弹窗外 | 关闭弹窗，取消进行中的请求 |
| 托盘右键 | 暂停/恢复监听、打开配置文件、退出 |

弹窗为无边框、不抢焦点设计：不干扰打字，鼠标截图选字都会被过滤（取不到选中文本就不会出现任何 UI）。

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

## 测试

```powershell
# LLM 链路：流式翻译 + 解释，打印首字延迟/总耗时
.venv\Scripts\python.exe test_llm.py

# 取词链：3 秒倒计时后去别的窗口选中文字，打印 text/rect/source
# 运行中输入 e 可加测 explicit（剪贴板兜底，会短暂占用并还原剪贴板）
.venv\Scripts\python.exe test_capture.py
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

OCR 截图翻译（qwen3-vl 自带视觉能力，只需把截图放 `images` 字段）、追问、自启动、打包 exe、管理员窗口支持。
正式版技术栈（Tauri 2 / WPF）待原型验证后再评估；capture.py 的取词逻辑可直接翻译到目标栈。
