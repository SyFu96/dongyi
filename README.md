<div align="center">

<img src="assets/dongyi-logo.png" width="96" alt="懂译 logo">

# 懂译 · dongyi

**越来越懂你的翻译。**

**Windows 划词翻译工具的 Rust / Tauri 重制版**：单文件、更小更快，
取词划词翻译 / 解释 / 追问 / 输入翻译，本地 Ollama 与联网 OpenAI 兼容（DeepSeek 等）双后端，
学科领域 + 术语表 + 翻译记忆 + 个人知识库（RAG）。

[![Release](https://img.shields.io/github/v/release/SyFu96/dongyi?filter=rust-*&label=rust%20release)](https://github.com/SyFu96/dongyi/releases/tag/rust-v0.1.0)
[![ci-rust](https://github.com/SyFu96/dongyi/actions/workflows/ci-rust.yml/badge.svg?branch=main)](https://github.com/SyFu96/dongyi/actions/workflows/ci-rust.yml)
![License](https://img.shields.io/badge/license-GPL--3.0--only-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4)
![Rust](https://img.shields.io/badge/Rust-2024-000000?logo=rust&logoColor=white)
![Tauri](https://img.shields.io/badge/Tauri-2-24C8DB?logo=tauri&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenAI%20compatible-000)

[下载安装包 / 绿色版](https://github.com/SyFu96/dongyi/releases/tag/rust-v0.1.0) · [Rust 源码与说明](dongyi-rs/README.md) · [数据与配置](#数据目录) · [反馈问题](https://github.com/SyFu96/dongyi/issues)

</div>

> **本仓库包含两个版本**：
> **`dongyi-rs/`（Rust / Tauri 重制版，主推，v0.1.0）** 与
> **根目录（Python 原版，v0.1.x，说明见 [PYTHON_VERSION.md](PYTHON_VERSION.md)）**。
> 两者共用 `%APPDATA%\dongyi\` 数据目录（配置 / 术语表 / 翻译记忆 / 知识库索引），可交替使用。
>
> 重制版收益（实测）：主程序 6.7 MiB、安装包 2.4 MiB；冷启动到就绪 ~0.7 s；稳态内存 ~33 MB；
> 无 Python 运行时依赖，单一可执行文件。

## 界面

ArtCraft Launcher 风：纸白底 + 1px 细线栅格 + 全直角 + 编号色块 + 等宽 micro-label。

| 译文（划词后自动翻译） | 解释（学科适配 + 术语） |
|---|---|
| ![译文](dongyi-rs/docs/screenshots/ui-translate.png) | ![解释](dongyi-rs/docs/screenshots/ui-explain.png) |

| 输入翻译（本地/联网 + 目标语向 + 存记忆校对） | 追问（结合原文的对话） |
|---|---|
| ![输入翻译](dongyi-rs/docs/screenshots/ui-input.png) | ![追问](dongyi-rs/docs/screenshots/ui-chat.png) |

设置窗为独立无边框窗口（左导航六组：模型 / 划词 / 热键 / 检索 / 外观 / 领域）。

## 安装与运行

- 安装包：`dongyi_0.1.0_x64-setup.exe`（NSIS，当前用户安装，免管理员）——[下载](https://github.com/SyFu96/dongyi/releases/tag/rust-v0.1.0)
- 绿色版：`dongyi_0.1.0_x64-portable.zip`（解压后双击 `dongyi.exe`）
- 常驻系统托盘；热键默认 `Ctrl+Alt+Shift+T/E/I`（翻译/解释/输入翻译）
- 从源码构建：见 [`dongyi-rs/README.md`](dongyi-rs/README.md)（`cd dongyi-rs && npx tauri dev`）

## 数据目录

`%APPDATA%\dongyi\`（与 Python 原版共用，可直接接力）：

| 路径 | 内容 |
|---|---|
| `config.json` | 全部配置（模型、热键、学科领域、知识库目录、主题等） |
| `app.log` | 运行日志（启动耗时、知识库刷新/告警、LLM 请求等；诊断入口） |
| `glossaries\*.csv` | 术语表，每行 `原文,译文[,备注]`，`#` 开头为注释 |
| `tm\general.jsonl`、`tm\dom_<学科>.jsonl` | 翻译记忆（`{"src","tgt","time"}` 每行一条） |
| `kb_index\index.json` | 知识库 BM25 索引（v4 格式，与 Python 原版互通） |

## 功能要点

- **划词**：UIA 取词 + 受控剪贴板兜底；防抖；浮标自动隐藏（防误触：取不到词不弹 UI）
- **翻译/解释/追问/输入翻译**：流式输出、可停止、追问上下文、输入翻译支持目标语向
- **双后端**：每个入口可切换本地 Ollama / 联网；联网 key 在设置页粘贴，留空回退环境变量
- **学科适配**：领域说明 + 术语表（词边界感知）+ 知识库片段 + 翻译记忆参考译例，按请求组装注入
- **翻译记忆**：「存记忆」支持**校对译文后保存**（请求配对，防新旧错配）
- **知识库**：txt/md/markdown/csv/json 直读；后台线程增量索引（mtime+size 复用）；BM25 检索
- **严格离线**：仅放行本机 Ollama（loopback），一律不外发云端
- **设置**：模型 / 划词 / 热键 / 检索 / 外观（跟随系统主题）/ 领域 六组；差异路径事务保存，失败不动旧配置

## 已知裁切与限制

- 知识库解析仅 txt/md/markdown/csv/json（UTF-8，非 UTF-8 按容错字符处理，无 GB18030 解码）；PDF/DOCX **不解析**
- PDF/DOCX 的既有缓存**保留条件**：该文件仍在已启用领域的 `kb_dirs` 扫描目录内、元数据可读、且不超过 20 MiB；
  满足条件且索引里已有其片段时会继续消费；源文件被删除/移出目录/超过 20 MiB 时，刷新会移除其片段
- 源文件变化但无法解析（PDF/DOCX）：本版**继续沿用旧缓存**（后台日志告警），旧内容不会自动失效
- 知识库额度：可解析文件受 5 万块上限（被截断文件标记不完整，容量释放后下次刷新补齐）；
  **不可解析类型的既有缓存全量保留、不受该上限约束**——总缓存量可能超出 5 万块
- 知识库索引初始化：**后台异步加载**，未就绪期间检索静默返回空；异常/超时自动重试，连续失败后暂停并保留待刷新目标
- 索引**磁盘保存失败**（权限/占用）：内存索引仍生效，**不自动重试**
- 术语表按 `csv.reader` 常用子集解析（引号仅在字段起始生效、支持跨行字段、CR/LF/CRLF）
- 弹窗开着时静默划词的浮标偶有不显示（已知限制；主流程用热键）
- 热键改动需重启应用生效

## 诊断与恢复（日志位置）

- **日志文件**：`%APPDATA%\dongyi\app.log`（含 `[boot]` 启动耗时、`[orch]` 编排、`[kb]` 知识库、`[llm]` 请求等）
- **知识库未就绪/暂停**：日志出现 `[kb] 索引初始化未就绪，本次刷新跳过`、`[orch] kb 初始化长时间未就绪，暂停自动重试`
  —— 非致命：翻译正常；稍后在设置保存一次或切换学科触发重试；持续失败检查目录权限/占用
- **索引保存失败**：日志出现 `[kb] 索引临时文件写入失败` 或 `索引替换失败` —— 内存索引仍可用；
  解除权限/占用后，在设置里**换到另一有效目录再切回**（或重启应用）触发真实重刷
- 本版**没有用户可见的诊断弹窗**；上述状态只体现在 app.log 中（已知限制）

## 已知限制（用户可见行为汇总）

| 现象 | 原因与建议 |
|---|---|
| 解释/追问里知识库内容暂时缺席 | 索引后台初始化中或正在重建；稍后重试；`app.log` 有告警可查 |
| 知识库里的 PDF/DOCX 内容**完全不出现** | 该文件从未被索引过（无既有缓存）：本版不解析该格式；转成 txt/md 后加入 |
| 知识库里的 PDF/DOCX 内容**与源文件最新版不一致** | 有旧缓存但源文件已更新：本版沿用旧片段（日志告警）；如需最新内容请转 txt/md |
| 存记忆提示"请先完成一次翻译" | 采用请求配对（防新旧错配）：需本页完成过一次翻译后，才可将该次结果校对保存 |
| 修改热键后不生效 | 热键在启动时注册，保存后重启应用 |

## 开发构建

```powershell
cd dongyi-rs
# 依赖：Node + Rust(MSVC)；桌面调试（前端热更）
npx tauri dev
# 发布构建（内嵌前端 dist + NSIS 安装包）
npx tauri build
# 工作区测试
cargo test --workspace
```

> 构建铁律：`frontendDist` 在编译期内嵌进 exe——改前端后必须 `npm run build` **并重编 exe**，只重启不重编不会生效。

## 仓库结构

```
dongyi-rs/                  Rust / Tauri 重制版（主推）
  src-tauri/                应用壳：三窗（弹窗/浮标/设置）、托盘、IPC、编排线程
  src/                      React 前端（三视图 + 主题）
  crates/dongyi-core/       配置读写（差异事务）、数据目录、单实例
  crates/dongyi-capture/    UIA 取词 + 剪贴板兜底（STA）
  crates/dongyi-trigger/    全局热键 / 鼠标钩子
  crates/dongyi-llm/        LLM 流式客户端、取消/预热/保活、联网检索
  crates/dongyi-knowledge/  领域 / 术语表 / 翻译记忆 / 知识库（BM25）
  docs/                     验收记录 + 阶段审查报告 + 界面截图
(根目录)                    Python 原版（v0.1.x）：app.py / popup.py / ...，说明见 PYTHON_VERSION.md
.github/workflows/          CI（ci.yml = Python 原版；ci-rust.yml = 重制版）
```

许可：GPL-3.0（沿用原版；第三方组件许可见 `dongyi-rs/THIRD_PARTY_NOTICES.md` 与 `dongyi-rs/THIRD_PARTY_LICENSES.txt`）。
