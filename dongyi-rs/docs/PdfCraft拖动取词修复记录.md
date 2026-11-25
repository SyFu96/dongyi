# PdfCraft 取词与译文公式修复（2026-11-25）

## 现象

- PdfCraft 0.22.0 中拖选文字后，懂译不出现「译」浮标；随后按 Alt+T 只得到
  “未获取到选区”。
- 译文里的公式显示为原始 `$R_i$`、`$R_{diff}$`、`$C_{diff}$`，没有排版。

## 根因

1. PdfCraft 是 egui/eframe 自绘，进程无 WebView2/Electron 子进程；UIA 没有可用的
   TextPattern，抓不到选区。日志中 `source=None` 与这一点一致。
2. PdfCraft 复制选区时会同时写 `CF_UNICODETEXT` 和 `HTML Format`。懂译静默兜底的
   可还原格式白名单原先只包含纯文本及其合成格式，遇到 HTML 直接跳过、不浮标。
3. 静默兜底仍会跳过**图片/文件/RTF 等不可原样还原的格式**。如果剪贴板里是微信
   截图图片，日志会出现 `[capture] 剪贴板含不可可靠还原的格式，静默跳过兜底`；
   这不是 HTML 修复失效，而是为了不破坏用户剪贴板里的图片。
4. PdfCraft/egui 收到 Alt 事件后，后续系统 `Ctrl+C` 不再被当作 Copy（隔离实例可
   稳定复现；控制通道 `edit.copy` 仍能复制，说明选区没丢）。这是 PdfCraft 侧的
   Alt 菜单/修饰键状态问题，Alt+T 在 PdfCraft 中仍不可靠。
5. 译文页此前用 `whitespace-pre-wrap` 纯文本渲染，没有走 Markdown/KaTeX；解释页
   已经走 `MarkdownContent`，所以只有解释里的公式正常。

## 修改

### 1. 保留 HTML 剪贴板（静默拖选）

`crates/dongyi-capture/src/lib.rs`：

- `ClipSnapshot` 增加 `html: Option<Vec<u8>>`，记录 `HTML Format` 原始字节。
- 备份快照允许“纯文本 + HTML Format”；HTML 读取失败或超过 16 MiB 时仍视为不可
  靠还原，静默路径跳过。
- 同步还原时先写回 `CF_UNICODETEXT`，再把 HTML 原始字节写回注册格式，避免为了取词
  破坏用户剪贴板中的富文本。
- 静默兜底被拒绝时记录具体原因，便于定位。
- 其他富格式（图片、文件、RTF 等）仍按原有策略跳过。

### 2. 显式热键读取当前剪贴板（手动 Ctrl+C 兜底）

同一文件：

- 新增 `clipboard_current_text`：只读 `CF_UNICODETEXT`，不发键、不改写剪贴板；
  终端窗口仍跳过。
- 显式路径顺序改为：UIA → 模拟 Ctrl+C → **当前剪贴板纯文本**。
- 新增配置 `clipboard_current_fallback`，缺省 `true`；设为 `false` 可关闭。
- 这样即使「译」浮标没出现，也可以先手动 Ctrl+C，再按 Alt+T 翻译剪贴板内容。

### 3. 译文公式渲染

`src/App.tsx`：

- 译文页从 `<div className="whitespace-pre-wrap">` 改为 `MarkdownContent`，与解释页
  共用 `remark-math` + `rehype-katex`。
- `src/index.css` 中 `.markdown-content p { white-space: pre-wrap; }` 保留译文原有
  换行，不会因走 Markdown 而合并成一段。

## 验证

- `cargo check -p dongyi-capture --all-targets` 通过。
- `npm run build` 通过；`node tools/check-markdown.mjs` PASS（行内/块级公式、货币
  符号、表格、代码块、非法 HTML 等用例）。
- `cargo build --release -p dongyi-rs` 通过；安装后 SHA256
  `773698C972BC1D78DE2FBD8B9305E76DBADE708BE800E89695BBF8D2A6C22A14`，
  启动日志显示 `[boot] ready` 与三个热键注册成功。
- 真实应用端到端验证（空白 Notepad，无选区）：模拟 Alt+T → 日志
  `[clipboard] current fallback chars=28` → `source=Some(Clipboard)` →
  `selected_chars=28`，弹窗正常打开。
- 诊断例子：`cargo run -p dongyi-capture --example probe_pdfcraft_capture`
  （会发送 Ctrl+C 并可能读取剪贴板，仅在测试窗口运行）。
- 静默拖选的 HTML 修复此前已由用户确认；图片剪贴板场景按设计仍跳过。
- 译文公式的实际视觉效果待用户在下一次翻译中确认。

## 已知限制

- 剪贴板含图片/文件/RTF 时，静默拖选不浮标；请先手动 Ctrl+C 复制文字，再按 Alt+T。
- PdfCraft 中 Alt+T 的 Ctrl+C 失效是 PdfCraft 侧问题；当前靠“读当前剪贴板”兜底，
  需要先手动复制一次。
- 当前剪贴板兜底会翻译剪贴板里已有的文本；如不需要，可在 `config.json` 设置
  `"clipboard_current_fallback": false`。

## 回滚

修复前二进制备份：`%LOCALAPPDATA%\dongyi\backup-pdfcraft-html-20261125-120935\dongyi-rs.exe`。
退出懂译后用它覆盖 `%LOCALAPPDATA%\dongyi\dongyi-rs.exe` 并重启即可。

## 参考

- Microsoft “Clipboard Formats”：`CF_UNICODETEXT`、注册格式 `HTML Format` 的 HGLOBAL 语义。
- PdfCraft 源码 `crates/ui-egui/src/app/clipboard.rs`：`copy_selected_text` 优先写
  `HTML` + `TEXT` 两种 flavor。
