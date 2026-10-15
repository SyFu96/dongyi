# 第三方组件与许可说明（THIRD PARTY NOTICES）

懂译（Dongyi）Rust 重制版在构建/运行中使用以下主要开源组件。
许可文本随各组件发布，完整列表见 `Cargo.lock` 与 `package-lock.json`。

## 运行时与框架

| 组件 | 版本（约） | 许可 |
|---|---|---|
| Tauri / tauri-build / tauri-plugin-* | 2.x | MIT 或 Apache-2.0 |
| WebView2 (Microsoft Edge WebView2 Runtime) | 系统组件 | Microsoft 专有许可（随 Windows 分发） |
| React / react-dom | 19.x | MIT |
| react-markdown / remark-gfm（含 unified / remark / rehype 依赖） | 10.x / 4.x | MIT（详见随附聚合许可） |
| @tauri-apps/api | 2.x | MIT 或 Apache-2.0 |

## Rust 依赖（主要）

| 组件 | 用途 | 许可 |
|---|---|---|
| serde / serde_json | 序列化、配置 | MIT 或 Apache-2.0 |
| tokio / tokio-util | 异步运行时、取消令牌 | MIT |
| reqwest | HTTP（流式、重定向策略） | MIT 或 Apache-2.0 |
| futures-util | 流工具 | MIT 或 Apache-2.0 |
| url | URL 解析 | MIT 或 Apache-2.0 |
| thiserror | 错误定义 | MIT 或 Apache-2.0 |
| log | 日志门面 | MIT 或 Apache-2.0 |
| windows (windows-rs) | Win32 API（UIA、全局钩子、显示器工作区） | MIT 或 Apache-2.0 |
| uiautomation（含 derive） | UIA 取词 | **Apache-2.0** |
| tauri-build / tauri-macros / tauri-utils | 构建与宏 | MIT 或 Apache-2.0 |

> 全局热键与鼠标/键盘钩子由 `windows` crate（Win32 低级钩子 WH_MOUSE_LL /
> WH_KEYBOARD_LL）实现，未使用独立的 global-hotkey/rdev 依赖。

## 随附许可文本

本软件以 GPL-3.0 发布（全文见同目录 `LICENSE`）。

**第三方组件的许可材料**见同目录 **`THIRD_PARTY_LICENSES.txt`**：
由 Cargo.lock 与 package-lock 依赖树聚合生成，采集规则与覆盖范围如下——

- 本地 cargo registry 中每个锁定 crate 的 `LICENSE*/LICENCE*/COPYING*/NOTICE*/NOTICES*` 原文
  （含上游归属文件，如 `cfg_aliases` 的 `NOTICES.md`）；
- 无上述文件的组件：从 crates.io 对应版本 `.crate` 归档补取；**归档内确实不含许可文件的上游
  （如 uiautomation、webview2-com 系列）**，条目中列明其许可标识（如 Apache-2.0/MIT）、
  `Cargo.toml` 的 authors/repository 归属摘录，并注明适用本文件内的共享许可全文——
  该判断可复核：下载同名 `.crate` 即可验证包内确无许可文件；
- 随前端打包的 npm 运行时组件列出其 LICENSE 文件（如仅有 `LICENSE.spdx` 元数据，
  则以 package.json 的 license 标识映射到共享全文）；
- Cargo.lock 同时覆盖构建期与跨平台依赖：条目为**全部锁定 package**（含本项目 6 个
  workspace 包——其许可为随附的 GPL-3.0 LICENSE，非第三方组件）；Windows 运行时依赖
  已按 `cargo tree --target x86_64-pc-windows-msvc -e normal` 的集合核对补充。

主要组件许可标识一览：

| 组件 | 许可 |
|---|---|
| Tauri / tauri-plugin-* | MIT 或 Apache-2.0 |
| uiautomation / uiautomation_derive | Apache-2.0 |
| windows (windows-rs) | MIT 或 Apache-2.0 |
| serde / serde_json / reqwest / futures-util / url / thiserror / log | MIT 或 Apache-2.0 |
| tokio / tokio-util | MIT |
| React / react-dom / scheduler | MIT（Copyright (c) Meta Platforms, Inc. and affiliates.） |
| @tauri-apps/api / plugin-opener | MIT 或 Apache-2.0 |

## 说明

- 本软件以 **GPL-3.0** 发布（沿用原 Python 版许可，全文见 `LICENSE`）；上述第三方组件各自保留其原始许可。
- **对应版本源码获取**：`release-artifacts\dongyi-0.1.0-source.zip` 即与本二进制 v0.1.0 对应的
  完整源码归档（`src/` 前端、`crates/` 与 `src-tauri/` 后端、`Cargo.lock`/`package-lock.json`
  锁定依赖版本）；亦可向作者索取（发布说明中的联系方式）。
- 本文件与 `LICENSE` 随安装包（安装目录）与绿色版 zip 一并交付；第三方许可全文见本文件「随附许可文本」。
- 联网检索功能会访问用户配置的检索服务端点（默认 ollama.com），翻译/解释的联网模式会访问
  用户配置的 OpenAI 兼容服务（如 DeepSeek）；使用相关功能受对应服务条款约束。
