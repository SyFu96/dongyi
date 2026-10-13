# P6-F 定点复审报告

日期：2026-10-13。**最终判定：PASS。可交付，待需求方人工验收。**

RE4 的最终字节不同步、NOTICES 计数口径及执行文档“493 crate／全部全文”表述问题均在本轮范围内闭合。M1/M2/M3 沿用上轮 PASS；本结论不代表人工安装、功能、性能验收已经完成。

## 1. 范围与方法

已读取上轮 GATE_REVIEW_P6_RE4.md、执行文档及 env-list 技能和环境参考。使用 PowerShell 5.1 的 Get-FileHash 与 .NET ZIP 只读流独立计算文件和归档内成员 SHA256；未解压落盘、运行产品、安装、编译、重新打包或修改冻结产物。唯一新增文件为本报告，未启动子代理。

核验范围为执行文档 §9/§10/§11、冻结产物与 SHA256SUMS.txt、NOTICES 口径、三份许可材料副本及安装器静态资源机制。未重开全依赖许可审计；未将历史日志当作最终 exe 性能证据。

## 2. 冻结产物与执行文档：PASS

| 产物（相对 dongyi-rs） | 实测字节 | MiB（1024²，两位） | 实测 SHA256 |
|---|---:|---:|---|
| release-artifacts/dongyi_0.1.0_x64-setup.exe | 2,506,497 | 2.39 | B7DBD1F7624431469851617628C3F69916A4C9A36ADF12A963F5B91461B6A5E3 |
| release-artifacts/dongyi_0.1.0_x64-portable.zip | 3,286,242 | 3.13 | 0309F8078E9CEA4BFEB6A97886D4EE3AB73575EFFCF126053AE591A89167CA59 |
| release-artifacts/dongyi-0.1.0-source.zip | 736,996 | 0.70 | 27616C29EC7A8EF0CAE3B6EE0DC3BD7AD1B6D9FCD871B561722528A925296053 |
| target/release/dongyi-rs.exe | 7,044,608 | 6.72 | 85BC1E65D1D408993E7E488975D8F6F786199AD64F20556EB7015F8D8CEB9D65 |

四项均与用户冻结值及 SHA256SUMS.txt 一致。构建目录 target/release/bundle/nsis 的 setup 与发行 setup 同字节、同哈希；绿色 ZIP 内 dongyi.exe 与 release 主程序同字节、同哈希。

执行文档为 ../Rust重构执行文档.md：

- §9 第 149 行的 setup/exe 字节与 MiB 一致；第 150 行（验收 #12）明确 615ms 为历史记录、728ms 为现存 app.log，并写明 run() 起点→setup 末尾口径及最终哈希产物未重新计时。
- §10 第 161–163 行的四项字节及 MiB 逐项一致；第 164–165 行重复说明计时出处与边界。
- §11 第 181 行的 setup/portable/source 字节一致，状态为“四轮复审基本闭合，许可主线 PASS”，保留待复审 F 与人工验收，不再作无条件全部整改完成声明。

现存 %APPDATA%/dongyi/app.log 为 305 B，含 `[boot] ready in 728ms`。它未绑定最终 exe 哈希，只支持该日志存在。第 141 行仍简写“实测 615ms”，但同节第 150 行及 §10 已明确历史限定；按本轮指定核验范围不构成残余阻断，也不接受其为最终产物已达到真实可交互启动门槛的独立证明。

## 3. NOTICES 与全部锁定 package 表述：PASS

THIRD_PARTY_NOTICES.md 第 48–50 行已删除“263 个”，明确 Cargo.lock 覆盖构建期与跨平台依赖，条目为全部锁定 package；其中 6 个 workspace 包属本项目，许可为随附 GPL-3.0 LICENSE，非第三方组件。Windows 集合核对命令明确为 `cargo tree --target x86_64-pc-windows-msvc -e normal`。

执行文档第 181 行已将“493 crate”改为“Cargo.lock 全部锁定 package”，并区分采集到的 LICENSE/COPYING/NOTICE 原文与无许可文件上游的归档复核、归属摘录和共享全文映射。NOTICES 第 38 行起也明确本地采集、归档补取、无文件映射及 npm SPDX 元数据边界，未再承诺每个条目都有独立许可全文。

这里的 Windows normal 依赖集合仍可能含 workspace、宏及相关依赖；修订文字表示集合核对补充，不解释为实际装入运行进程的第三方组件数。本轮未重新执行 cargo tree；集合覆盖与许可映射沿用 RE4 的核验，聚合许可文件哈希也与 RE4 相同。

## 4. 许可交付副本：PASS（安装包为静态证据）

以下每项在工作区根目录、target/release 资源副本、绿色 ZIP 根目录及源码 ZIP 的 dongyi-rs 根目录中均逐字节 SHA256 相同；每个 ZIP 均找到对应三份材料。

| 材料 | 字节 | 四处一致的 SHA256 |
|---|---:|---|
| LICENSE | 34,674 | FB981668C18A279E285FC4D83FBA1E836CC84DD4DAA73C9697D3CFD2D8ACA6E0 |
| THIRD_PARTY_NOTICES.md | 4,119 | 25F7928F1B9B8EDB62BF18A26A3D96D213BE486A8A6F8199957664D0008AF6AF |
| THIRD_PARTY_LICENSES.txt | 3,978,883 | B9CAFB1ED4F9F37A904A93B06CFCD0B35724B9D18DA645BF98F2F431C2127AB8 |

三处交付指安装包资源链、绿色包、源码包。src-tauri/tauri.conf.json 的 resources 映射三份材料；target/release/nsis/x64/installer.nsi 第 649–651 行从工作区对应文件复制到安装目录，卸载段删除对应材料。发行与构建 setup 同哈希，静态交付机制及可直接读取的副本一致性通过。

本轮未独立解包 NSIS 内部资源或安装产品，因此不把资源副本、生成脚本与 setup 同哈希夸大为实际安装目录材料已实测一致；该项保留人工安装验收。源码归档存在也不证明可复现构建或源码与二进制的独立对应。

## 5. 剩余人工验收清单

沿用 RE4 延期清单，本轮均未运行；须使用隔离数据或备份，绑定本报告冻结哈希并保留逐项证据。

1. 原 10 项：拖选、双击、双向翻译、剪贴板还原、防误触、取消、热键、报错、50 次稳定性、混合缩放双屏；#14 UIA 命中划词→浮标 ≤400ms。
2. 最终产物启动日志与真实可交互时间、托盘就绪、WorkingSet/Private、无控制台 [boot]/[orch]/[kb]、日志权限失败；历史 615/728ms 不替代最终性能验收。
3. 中文安装向导、当前用户免管理员、默认/自选目录、快捷方式、WebView2 缺失引导、单实例、运行中升级；实际安装目录 LICENSE/NOTICES/THIRD_PARTY_LICENSES 逐文件哈希与本报告一致，并核验对应源码获取路径。
4. 升级/卸载及删除应用数据选项前后比对 config/CSV/JSONL/v4 索引；Python→Rust→Python 往返与旧 TM 命名续用，避免并发写同一数据集。
5. TM 完成 A→B 在途/失败→存记忆、校对配对；长领域名、窄窗、热键重启生效。
6. KB 49999+2、不可解析缓存超 50000、room=0、额度释放/incomplete；PDF/DOCX 无缓存/陈旧缓存、删除/移出/超过20MiB、非 UTF-8 边界。
7. KB 慢初始化 A→B→C、50 轮耗尽后恢复、线程创建失败；隔离保存失败，核验内存可用/磁盘失败、同目标去重，换另一有效目录再切回及重启恢复。

**本轮定点复审 PASS，无本轮必修残余。可交付，待需求方人工验收。**
