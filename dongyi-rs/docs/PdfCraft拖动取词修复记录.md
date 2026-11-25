# PdfCraft 拖动取词不显示「译」修复（2026-11-25）

## 现象

在 PdfCraft 0.22.0 中拖选文字后，懂译不出现「译」浮标；随后按 Alt+T 也只得到
“未获取到选区”。

## 证据与原因

- PdfCraft 是 egui/eframe 自绘，进程无 WebView2/Electron 子进程；UIA 没有可用的
  TextPattern，抓不到选区。日志中 `source=None` 与这一点一致。
- 在隔离实例中拖选并执行 `edit.copy`，用 `EnumClipboardFormats` 观察到 PdfCraft
  写入：`CF_UNICODETEXT`、`HTML Format`、`CF_TEXT`、`CF_OEMTEXT`、`CF_LOCALE`。
- 懂译静默（拖选）兜底的可还原格式白名单 `TEXT_FORMAT_OK` 只包含纯文本及其合成
  格式；遇到 `HTML Format` 判定为不可纯文本还原，直接跳过、不浮标。显式热键路径
  允许富格式，所以不受这条限制。
- 显式 Alt+T 在 PdfCraft 中还会遇到另一个独立问题：PdfCraft/egui 收到 Alt 事件后，
  后续系统 Ctrl+C 不再被当作 Copy（隔离实例可稳定复现；控制通道 `edit.copy` 仍能
  复制，说明选区没有丢）。本修复不改变这一点；PdfCraft 中请优先用拖选后的「译」
  浮标，或改用不含 Alt 的热键。

## 修改

`crates/dongyi-capture/src/lib.rs`：

- `ClipSnapshot` 增加 `html: Option<Vec<u8>>`，记录 `HTML Format` 原始字节。
- 备份快照允许“纯文本 + HTML Format”；HTML 读取失败或超过 16 MiB 时仍视为不可
  靠还原，静默路径跳过。
- 同步还原时先写回 `CF_UNICODETEXT`，再把 HTML 原始字节写回注册格式，避免为了取词
  破坏用户剪贴板中的富文本。
- 静默兜底被拒绝时记录具体原因（白名单/终端/格式），便于下次定位。
- 其他富格式（图片、文件、RTF 等）仍按原有策略跳过。

## 验证

- `cargo check -p dongyi-capture --all-targets` 通过。
- `cargo test -p dongyi-capture`：SAFEARRAY 用例通过；剪贴板竞争用例因当时 Windows
  会话锁屏、`OpenClipboard` 不可用而失败（环境原因）。
- `cargo build --release -p dongyi-rs` 通过；安装后 SHA256
  `C5D4BB9676CA91C98A44D9894F2537643137FB9F111CE62162826E8D040AB58F`，
  启动日志显示 `[boot] ready` 与三个热键注册成功。
- **用户已确认（2026-11-25）**：解锁后 PdfCraft 拖选 → 等待约 0.2–0.5 s →
  「译」浮标正常出现并可点击翻译。可用诊断例子复现：
  `cargo run -p dongyi-capture --example probe_silent_pdfcraft`
  （会向前台 PdfCraft 发送 Ctrl+C 并还原剪贴板，仅用于测试窗口）。

## 回滚

修复前二进制备份：`%LOCALAPPDATA%\dongyi\backup-pdfcraft-html-20261125-120935\dongyi-rs.exe`。
退出懂译后用它覆盖 `%LOCALAPPDATA%\dongyi\dongyi-rs.exe` 并重启即可。

## 参考

- Microsoft “Clipboard Formats”：`CF_UNICODETEXT`、注册格式 `HTML Format` 的 HGLOBAL 语义。
- PdfCraft 源码 `crates/ui-egui/src/app/clipboard.rs`：`copy_selected_text` 优先写
  `HTML` + `TEXT` 两种 flavor。
