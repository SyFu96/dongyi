# P6-E 定点复审报告

日期：2026-10-13。**最终判定：FAIL（仅文档 MINOR 残余）。** 上轮 M1/M2 的 NOTICE 遗漏、无本地许可文件组件的映射依据已闭合，M3 沿用闭合。M4 的启动日志边界已补充，但执行文档仍用上一版产物精确字节；许可说明的“263 个 Windows 运行时依赖”口径也需纠正。本次 FAIL 表示要求逐条闭合的发布一致性尚未完成，不表示仍存在上轮许可 MAJOR。

## 1. 范围与方法

只读检查工作区、registry、node_modules、发行 ZIP、NSIS 脚本及日志；使用 PowerShell 5.1/.NET 内存 ZIP 流、Node 内存脚本和 `cargo tree --offline --locked --target x86_64-pc-windows-msvc -e normal --prefix none --format '{p}'`。已读取 env-list 环境参考；未使用 Python、安装依赖、运行产品 exe、安装、编译或重新打包，未启动子代理。唯一新增交付文件为本报告。

七个上游包按 Cargo.lock 版本和 checksum 核验归档。六个从 `https://static.crates.io/crates/{name}/{name}-{version}.crate` 重新下载并在内存解压；webview2-com-sys 在线下载未完成，停止本次下载辅助进程后，改读本地 registry cache 的同名原始 .crate（5,768,930 B），SHA256 与 Cargo.lock 完全一致。没有把“下载成功 fetched=0”或本地源码目录无文件当成独立证明。

未找到交付的聚合脚本 v2/v3 文件，因此不宣称已逐行审核这两个脚本；对采集结果及补取/映射依据作独立核验。安装器证据限于配置、生成脚本、资源副本与发行/构建安装器同哈希，未独立解包安装器或验证安装目录。源码归档与工作区一致不证明可复现构建或二进制与源码独立对应。本报告不扩展为全依赖法律合规审计。

## 2. 最终发行物：PASS

| 文件 | 实测字节 | MiB（1024²，两位） | SHA256 |
|---|---:|---:|---|
| release-artifacts/dongyi_0.1.0_x64-setup.exe | 2,507,027 | 2.39 | 36D024B75A6609BCB5068C17FA4DAE3D6F666C42BC51ED8595422922AAF55664 |
| release-artifacts/dongyi_0.1.0_x64-portable.zip | 3,286,145 | 3.13 | 1D55215046D46F78EAF2772C80915C2361BC1B18F409C93735ACD9F08D987666 |
| release-artifacts/dongyi-0.1.0-source.zip | 730,280 | 0.70 | FF736F8AF51713DD33C23CEF0896FFAEAFCBFC510CE208A781C787962A970881 |
| target/release/dongyi-rs.exe／绿色包 dongyi.exe | 7,044,608 | 6.72 | C1F1545A8695957D9FDC18CD2334D0BFF62DD8318F4C8FCBA901565AA6DBE301 |

均与用户给定值及 SHA256SUMS.txt 一致；发行 setup 与 target/release/bundle/nsis 同名文件同哈希。

绿色包恰为 6 个根文件：dongyi.exe、README.txt、README.md、LICENSE、THIRD_PARTY_NOTICES.md、THIRD_PARTY_LICENSES.txt。除 README.txt 无工作区对应文件外，其余逐文件 SHA256 全部一致，exe 对应 release 主程序。

源码 ZIP 为 **101 条目＝98 文件＋3 目录条目**。规范化反斜杠与 dongyi-rs 根前缀后，98 个文件全部与工作区对应文件同哈希。相较上轮 97 个文件有所增加，未沿用旧数量。

## 3. M1/M2 许可主线：PASS，旧 MAJOR 闭合

### 3.1 NOTICE 与本地采集结果

THIRD_PARTY_LICENSES.txt:3 明列 LICENSE*/LICENCE*/COPYING*/NOTICE*/NOTICES*。对锁定 registry 组件根目录匹配文件重新核验：**787 个文件原文全部存在于对应组件段，其中 NOTICE 文件 1 个**。比较仅规范化 CRLF/LF 与首尾空白，不宣称逐字节保留原换行。

cfg_aliases 0.2.2 段始于 :7622，含 :7638 的 tectonic_cfg_support::target_cfg! 归属文字；本地 cfg_aliases-0.2.2/NOTICES.md 全文经上述规范化后在对应段完整匹配。上轮 NOTICE 遗漏已闭合。

聚合文件实际 **3,978,883 B**，499 个分隔段＝487 个 registry crate＋6 个本项目 workspace package＋5 个 npm 包＋1 个共享 MIT 文本段。执行文档的“Cargo.lock 493 crate”可解释为全部锁定 package 数，不能将其都称作第三方组件。6 个本项目段的空 license 映射不作为新增第三方缺口，本项目 GPL LICENSE 已随附。

### 3.2 七个无本地许可文件的包

对每个 .crate 的全归档成员名检查 LICENSE*/LICENCE*/COPYING*/NOTICE*/NOTICES*，七个均为零，不只检查根目录。归档 SHA256 均与 Cargo.lock checksum 一致；聚合段的 authors（上游有该字段时）、description、license、repository 摘录逐行均能在归档内 Cargo.toml 找到。

| 包／锁定版本 | 归档成员数 | 许可映射 | 聚合段起始行 | .crate SHA256 |
|---|---:|---|---:|---|
| uiautomation 0.25.1 | 23 | Apache-2.0 | 60514 | fa2eacf9390a8491bc949b04230f40c12520c6423a2962a6087eea1ef14373af |
| uiautomation_derive 0.7.9 | 10 | Apache-2.0 | 60523 | 1c893ec96e05c3c81ba46f838f3190549ec185ef377d582ab3d44202b2dfacbd |
| webview2-com 0.39.1 | 11 | MIT | 65411 | 3f89fca7a704cee10dcb3654c1dbb8941d1783132f1917358af75bec37a7d7e6 |
| webview2-com-macros 0.8.1 | 7 | MIT | 65419 | 67a921c1b6914c367b2b823cd4cde6f96beec77d30a939c8199bb377cf9b9b54 |
| webview2-com-sys 0.39.1 | 19 | MIT | 65427 | b3a07132775117d6065853d9d1178157b8c90e228de47129d6bce2c7edebedfb |
| alloc-stdlib 0.3.0 | 12 | BSD-3-Clause | 303 | 0b5c1865780388bfa186411ab5f247819487fc4864c6e9c3106611fa347586e1 |
| selectors 0.38.0 | 22 | MPL-2.0 | 45317 | 8adfa1c298912827b8a28b223b3b874357397ae706e6190acd9bf28cee99114d |

各段确含 `upstream: no license file in package; shared license text ... applies`，已由仅列标识改为可复核的包内容判断、许可映射与归属摘录。共享 MIT 独立段位于 :75020；Apache 第 1～9 节、结束标记及附录已有随附全文；BSD-3-Clause 可定位到 alloc-no-stdlib 段 :285 起（含 Dropbox 版权、三条件及免责）；MPL-2.0 全文可定位到 :11564 起，含第 10 节。接受为上轮要求的共享文本映射依据，不宣称补取到了不存在的组件许可文件。

### 3.3 npm 与 notices

react 19.3.0、react-dom 19.3.0、scheduler 0.28.0 的 LICENSE 原文含 Meta 版权行，仍在各自段落完整匹配。@tauri-apps/api 2.12.3 的两份许可与 SPDX 原文均匹配。

@tauri-apps/plugin-opener 2.7.1 段 :75346 包含原 LICENSE.spdx（含 Tauri 归属/版权元数据），段头 `license: MIT OR Apache-2.0` 与 package.json 一致。THIRD_PARTY_NOTICES.md:46 明确 SPDX 仅为元数据，通过 package.json license 映射共享全文，未继续将 SPDX 本身称为完整条款；该缺口闭合。

notices:38 起已说明采集范围、归档补取、复核方式和共享映射，虽章节仍题为“随附许可文本”，其内容已达到要求的覆盖规则与映射依据。已删除“每个组件都含全文和版权行”的泛化承诺。

### 3.4 三处交付一致性

| 材料 | SHA256（工作区／release 资源副本／绿色包／源码包一致） |
|---|---|
| LICENSE | FB981668C18A279E285FC4D83FBA1E836CC84DD4DAA73C9697D3CFD2D8ACA6E0 |
| THIRD_PARTY_NOTICES.md | 2AF4935903D238F9DEDD2079DBEBEF7AC9CB379F4FF0B8AA143BEE5A6614D49C |
| THIRD_PARTY_LICENSES.txt | B9CAFB1ED4F9F37A904A93B06CFCD0B35724B9D18DA645BF98F2F431C2127AB8 |

tauri.conf.json resources 映射三份；target/release/nsis/x64/installer.nsi:649–651 复制，:770–772 删除。静态机制与副本一致性通过，实际安装验收仍延期。

## 4. M3：沿用 PASS

README.md SHA256 仍为 2A91F93965B4B43FF6E6C87B4FB4B499C8E74B363F5764105C56A563466579A5，并与两份 ZIP 内副本一致。未重开已闭合的缓存前提、故障日志及保存失败恢复文档问题；真实故障恢复仍需人工运行窗口。

## 5. M4 与文档口径：部分闭合，MINOR 残余

**已闭合：** Rust重构执行文档.md:150（§9 第 12 项）已区分历史 615ms／现存 app.log 728ms，注明 run() 起点→setup 末尾口径及最终哈希产物未重新计时；§10:164–165 同样注明边界。现存日志本次为 305 B，仍含 `[boot] ready in 728ms`，未绑定最终 exe 哈希，因此只支持日志存在，不支持最终产物性能实测。§11:181 已改“四轮整改”，许可文字已收窄为采集与映射材料。

**RE4-m1／MINOR，未闭合：最终体积仍不同步。** Rust重构执行文档.md:149、:161–163、:181 仍写旧 setup 2,505,334 B、portable 3,281,763 B、source 720,088 B；实际分别是 **2,507,027 B、3,286,145 B、730,280 B**。源码在 §10 的 0.69 MiB 也应为 **0.70 MiB**。720,088 B 确已新增，但它是上轮归档体积，不能证明本轮“最终源码精确字节”闭合。exe 7,044,608 B 与其 6.72 MiB 正确；setup/portable 两位 MiB 未变化。建议只同步执行文档最终值，并在复审完成前避免“整改完毕”无条件声明。§9:141 的历史“实测 615ms”应一并加历史标签，与 :150 对齐。

**RE4-m2／MINOR，计数说明不精确：** THIRD_PARTY_NOTICES.md:48 的“Windows 运行时依赖 263 个”可复现为上述 `cargo tree -e normal` 去重后的 **263 个名称＋版本**，但包含 **6 个本项目包，第三方为 257 个**，且树中明确有 uiautomation_derive、tauri-macros 等 proc-macro 及其依赖，不能等同于 263 个实际装入运行进程的第三方组件。建议注明目标、命令、去重规则和 workspace/proc-macro 边界，改称 Windows 目标 normal 依赖树条目。该问题不否定七个组件的映射，也不重新升级许可 MAJOR。

## 6. 必修与判定

1. 同步执行文档 §9／§10／§11 的最终 setup、portable、source 字节，源码 MiB 改为 0.70，明确历史计时标签。
2. 收窄 notices 的 263 个口径，避免将含 workspace 和宏依赖的 normal 树宣称为实际运行第三方清单。

本轮不修改整改材料、不重打包。若后续修改随包 notices，实施方需自行同步交付副本、更新受影响归档与哈希；本报告不授权或执行打包。聚合脚本 v2/v3 未交付属于方法证据边界，不单独新增阻断。

**最终判定：FAIL，剩余均为 MINOR。许可主线 PASS、M3 PASS；M4 的最终发布文档一致性及计数表述未全部闭合。**

## 7. 剩余人工验收清单（沿用延期，本轮未运行）

1. 原 10 项：拖选、双击、双向翻译、剪贴板还原、防误触、取消、热键、报错、50 次稳定性、混合缩放双屏；#14 UIA 命中划词→浮标 ≤400ms。
2. 绑定实际验收的最终发行哈希与启动日志；验证无控制台 [boot]/[orch]/[kb]、真实可交互时间、WorkingSet/Private、日志权限失败情形。历史 615/728ms 不替代此项。
3. 中文安装向导、当前用户免管理员、默认/自选目录、快捷方式、WebView2 缺失引导、单实例、运行中升级；实际安装目录三份许可材料逐文件哈希及对应源码获取路径。
4. 升级/卸载及删除应用数据选项前后比对 config/CSV/JSONL/v4 索引；Python→Rust→Python 往返与旧 TM 命名续用，避免并发写同一数据集。
5. TM 完成 A→B 在途/失败→存记忆、校对配对；长领域名、窄窗、热键重启生效。
6. KB 49999+2、不可解析缓存超 50000、room=0、额度释放/incomplete；PDF/DOCX 无缓存/陈旧缓存、删除/移出/超过20MiB、非 UTF-8 边界。
7. KB 慢初始化 A→B→C、50 轮耗尽后恢复、线程创建失败；隔离保存失败，验证内存可用/磁盘失败、同目标去重，换另一有效目录再切回及重启的恢复路径。

人工验收须在允许运行/安装的窗口用隔离数据或备份并保留逐项证据，不作为本次文档必修项的替代。
