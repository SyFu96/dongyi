# P6 Gate 审查 Brief（收尾：打包 / 文档 / 发布一致性）

你是阶段审查人，审查『懂译』Python→Rust 重构 **P6 阶段**（打包、安装、文档、发布一致性）。

## 背景（必读）
- 执行文档：`D:\划词小工具\Rust重构执行文档.md`（§8 工期表 P6 行、§10 收益/实测、§11 阶段记录）
- P5 闸门报告链（约束延续 + 移交给 P6 的关注点）：`GATE_REVIEW_P5.md`、`GATE_REVIEW_P5_RE.md`、`GATE_REVIEW_P5_RE2.md`、**`GATE_REVIEW_P5_RE3.md`（PASS，末尾 P6 关注点 1~5）**
- Python 基线：`D:\划词小工具\划词小工具\`（LICENSE 为 GPL-3.0）

## P6 交付物（本轮审查对象）
1. **release 构建产物**（`dongyi-rs\target\release\`）：
   - 主程序 `dongyi-rs.exe`；安装包 `bundle\nsis\dongyi_0.1.0_x64-setup.exe`（**2.34 MiB**）
   - 发布目录 `dongyi-rs\release-artifacts\`：`dongyi_0.1.0_x64-setup.exe`、`dongyi_0.1.0_x64-portable.zip`（dongyi.exe + README.txt）、`SHA256SUMS.txt`
2. **bundle 配置**（`src-tauri\tauri.conf.json`）：`targets: ["nsis"]`、`windows.nsis = { languages: ["SimpChinese"], installMode: "currentUser" }`、icons 全套、`beforeBuildCommand: npm run build`、`frontendDist: ../dist`
3. **文档**：`dongyi-rs\README.md`（用法/数据目录/裁切与限制/构建铁律/目录结构）、`dongyi-rs\THIRD_PARTY_NOTICES.md`（GPL-3.0 声明 + 依赖许可表）、`dongyi-rs\LICENSE`（GPL-3.0 全文，复制自 Python 版）
4. **实测数据**（写入执行文档 §10）：exe 6.71 MiB、冷启动 ≈0.81s（release 版启动到编排首条日志）、稳态内存 WorkingSet ≈40.1 MB / Private ≈10.6 MB
5. **数据/升级策略**：数据目录 `%APPDATA%\dongyi\`（与 Python 版共用）；NSIS currentUser 安装不触碰该目录

## 复审方法（只读为主）
- 核对文件存在性、体积、SHA256SUMS 与实际产物**复算一致性**（`Get-FileHash`）
- 核对 tauri.conf bundle 配置与 Tauri 2 schema 合法性（可查本机 tauri-cli/`@tauri-apps/cli` 版本 2.x 的 schema；发行目标为 Windows x64）
- README/THIRD_PARTY_NOTICES 与**源码事实**一致性抽查：裁切（KB 仅 txt/md/csv/json、PDF/DOCX 保留缓存）、额度语义（不可解析缓存全量保留可能超 5 万块）、构建铁律（frontendDist 编译期内嵌）、已知限制（静默划词浮标、热键需重启）、数据文件格式（config.json/glossaries/tm/kb_index v4）
- LICENSE 与 Python 版一致（GPL-3.0）；第三方许可表是否覆盖主要直接依赖（可对照 `Cargo.toml`/`Cargo.lock`、`package.json`）
- 安装不覆盖用户数据的**机制层面**核对（NSIS 安装路径 vs `%APPDATA%`；卸载/覆盖升级行为）
- 上轮 P5 复审移交的关注点在 P6 文档/实现中的落地情况（恢复时延与暂停反馈、持久化失败可辨认、额度语义、发布一致性、升级保留数据）
- 允许 `cargo test --workspace --locked` 复跑与读取产物；**禁止启动/安装/运行产品 exe（需求方桌面运行中）**；禁止重新打包（会占用/改写产物）

## 产出要求
每交付项证据（文件/行号/命令输出）+ 结论；新发现按 BLOCKER/MAJOR/MINOR 分级（文件:行/原因/建议）；如 FAIL 给必修清单；末尾给出**发布前剩余人工验收项**（安装向导、快捷方式、数据保留、Python↔Rust 续用等）；最终判定 **PASS（可交付/待需求方人工验收）/ FAIL**。报告写 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P6.md`。
