# P6-D 定点复审报告

日期：2026-10-13。**最终判定：FAIL。** 上轮 Apache 非全文与 React 缺版权行两个具体缺口已修复；但第三方许可材料主线尚未整体闭合：聚合规则遗漏上游 NOTICES，部分实际 Windows 依赖仅列许可标识，缺少组件原始版权/归属材料。M3 沿用闭合；M4 精确产物体积及 MiB 已修正，文档来源边界与“全文/整改完毕”声明仍有 MINOR 残余。

## 范围与证据边界

按 GATE_REVIEW_P6_RE2.md 残余只读核验。读取 env-list 技能及环境参考，使用 PowerShell 5.1/.NET ZIP 内存流、Node 内存脚本核验文件与本地 registry/node_modules，查阅 Apache 与 OSI 官方文本。仅新增本报告；没有启动或安装产品 exe，没有构建、重新打包、安装依赖或修改交付文件，也没有运行编译脚本。未启动子代理。

安装包证据仍限于资源配置、installer.nsi、资源副本和发行/构建安装器同哈希，未独立解包安装器或验证安装结果。源码文件一致性不证明可复现构建，也不独立证明二进制对应源码。Cargo.lock 覆盖跨平台及构建依赖，不能把全部 487 个 crate 都认作 Windows 实际运行组件。本报告不是全依赖法律合规审计。

## 1. 最终发行物核验：通过

| 文件 | 实际字节 | MiB（1024²，两位） | SHA256 |
|---|---:|---:|---|
| release-artifacts/dongyi_0.1.0_x64-setup.exe | 2,505,334 | 2.39 | 2478663A30D27834824059A533ED2058CE5FE6A0A977A3547E78F2B4E96F3ADB |
| release-artifacts/dongyi_0.1.0_x64-portable.zip | 3,281,763 | 3.13 | EB89EA47466E072E3C7B6A592496E6E7ED0D84EC453EB3C000B65E55C4F5B41F |
| release-artifacts/dongyi-0.1.0-source.zip | 720,088 | 0.69 | B9A092D655D7794DF321D028C5E863727BD0BC9F37110FE10DFD03893E395FCD |
| 绿色包 dongyi.exe / target/release/dongyi-rs.exe | 7,044,608 | 6.72 | B3E5B91C89E4059BF190D894D2560BB45387FBAC60FB04A1860337E772EC99AA |

全部与用户给定哈希及 SHA256SUMS.txt 一致。setup 与 target/release/bundle/nsis 同名安装器同哈希；程序哈希在清单注释中，不冒充独立发行文件。

绿色 ZIP 恰有 6 个根文件：dongyi.exe、README.txt、README.md、LICENSE、THIRD_PARTY_NOTICES.md、THIRD_PARTY_LICENSES.txt。除没有工作区对应文件的 README.txt 外，其余逐文件 SHA256 与工作区对应文件一致，exe 对应 target/release/dongyi-rs.exe。

源码 ZIP 为 **100 条目＝97 文件＋3 目录条目**，不是 100 个文件。规范化 ZIP 中的反斜杠和 dongyi-rs 根前缀后，97 文件全部与工作区逐文件 SHA256 一致；含前后端、锁文件、配置、dist、图标及三份许可材料，无 target/node_modules。源码渠道沿用通过；实际对外发布仍须同时提供此归档。

## 2. M1/M2：具体旧缺口修复，整体仍 FAIL

### 已闭合的证据

- 聚合文件实际 3,960,082 B（3.96 MB，3.78 MiB），492 个组件段＝487 个 registry crate＋5 个 npm 组件。487 个 crate 的名称/版本均能与 Cargo.lock 对应；对 registry 根目录可见的 785 个 LICENSE*/COPYING* 文件逐个检查，原文在对应组件段内均存在（仅规范化 CRLF/LF、忽略文件首尾空白，不宣称聚合文本逐字节保留换行）。
- Apache-2.0 实际第 1～9 节、条款结束标记及附录已存在，已非上轮的简述加附录模板。官方第 4 节要求随附许可副本及适用的上游归属声明。[Apache 官方全文](https://www.apache.org/licenses/LICENSE-2.0.txt)
- react 19.3.0、react-dom 19.3.0、scheduler 0.28.0 的 LICENSE 原文均在各自段落，包含 Meta Platforms 版权行及 MIT 授权、免责文字。React 段始于聚合文件第 74713 行；notices 同样列出版权行。MIT 声明保留要求已有实际材料支撑。[OSI MIT 文本](https://opensource.org/license/mit)
- @tauri-apps/api 2.12.3 段含 LICENSE-APACHE-2.0、LICENSE-MIT 与 LICENSE.spdx；plugin-opener 2.7.1 版本及许可标识也已列出，但后者内容完整性另见残余。
- tauri.conf.json 的 bundle.resources 映射三份材料；installer.nsi:649–651 复制三份，:770–772 卸载删除。工作区、target/release 资源副本、绿色包及源码包三份材料的 SHA256 均一致。聚合文件哈希 AACD45DA42527823EB2D84B781D8CA6AD665F9157AED098DC29BA910E3FBD6F2；notices 哈希 54AC4C8037DE607122BD6EB1A73CF54C161A391E11E6A25F80AB00F14C0C1EB7；GPL LICENSE 哈希 FB981668C18A279E285FC4D83FBA1E836CC84DD4DAA73C9697D3CFD2D8ACA6E0。
- uiautomation 与 derive 的 Apache-2.0 元数据、低级钩子描述及随附机制沿用通过。

### MAJOR 残余：聚合规则不等于完整许可材料（延续 M1/M2，同一主线）

**遗漏上游声明。** 本地 cfg_aliases-0.2.2/NOTICES.md 是独立的第三方归属文件，说明 cfg_aliases! 使用 tectonic_cfg_support::target_cfg! 的代码并附许可说明。聚合文件只收 LICENSE*/COPYING*，没有这份 NOTICES.md，也没有其中的 tectonic_cfg_support 归属文字。源码归档也不携带依赖 registry 或该文件。上轮明确要求保留适用的上游 NOTICE；本轮采集规则未覆盖它。

**空许可段未补足组件材料。** 487 个 crate 中有 41 个根目录无 LICENSE*/COPYING* 文件，对应段只有 license 字段。部分属于其他平台，不能一律判作本 Windows 二进制缺陷；但不能据此声明每个组件都附了全文和版权行。具体 Windows 相关例子：

- uiautomation 0.25.1 / uiautomation_derive 0.7.9：聚合文件:60246–60251 只有 Apache-2.0 标识。crates/dongyi-capture/Cargo.toml:11 直接引用 uiautomation。别处已有 Apache 通用全文，故不再重复判“Apache 条款缺失”，但其上游版权/归属材料是否需保留、是否已有收录没有证据。
- webview2-com 0.39.1 / macros 0.8.1 / sys 0.39.1：聚合文件:65131 起只有 MIT 标识。本地 target/release/build 有 webview2-com-sys 构建引用及 x64 链接路径，不能简单当作非 Windows 平台依赖排除。其他 crate 的 MIT 文本及版权不能替代这些组件自身的声明；需取得对应版本上游许可/版权材料并核对。
- npm @tauri-apps/plugin-opener 2.7.1：聚合文件:75018 起只含 LICENSE.spdx（PackageLicenseDeclared/PackageCopyrightText 等元数据），没有该组件许可条款原文。共享通用条款可减少重复，但应明确对应关系、选用许可及所需组件归属材料，不能将 SPDX 文件称为许可全文。

整改要求：采集 NOTICE*/NOTICES*，对没有本地完整材料的**实际分发组件**按锁定版本补取上游许可、版权/归属文件，或提供可复核的排除/共享文本映射依据；同步交付副本。不要仅依据“registry 没有文件”或官方链接认定已履行随附要求。此处不要求为所有跨平台锁定依赖盲目补材料。

## 3. M3：沿用闭合

本轮不重开 M3。绿色包 README.md 与工作区一致，哈希仍为 2A91F93965B4B43FF6E6C87B4FB4B499C8E74B363F5764105C56A563466579A5；源码包对应文件也一致。缓存四项前提、日志位置、保存失败恢复路径与上轮结论保持一致。实际故障恢复及无控制台日志仍属于授权运行窗口的人工验收。

## 4. M4：体积闭合，文档声明部分未闭合（MINOR）

执行文档 §9:149、§10:161–163、§11:181 的 setup/exe/portable 数值及两位 MiB 与最终文件相符，旧 2.99 MiB 已消除；源码 0.69 MiB 正确。**源码精确 720,088 B 在执行文档中仍未出现**，§11 也只有 MiB，故“§9/§10/§11 已同步全部最终精确字节”的整改明细强于实际内容。

§10:164–165 已区分历史 615ms、现存日志 728ms，并注明最终产物未重新计时。§9:141、150 仍只写“实测 615ms”和达标，没有同处说明历史来源、728ms 出处和最终产物关联边界；§11 仍以“实测 615~728ms ≤1s”汇总。此前要求 §9/§10 明确边界，§9 尚未完成。≤1s 门槛与 run()→setup 末尾口径沿用通过，不能据历史日志证明最终哈希的冷启动或真实可交互性能。

notices 已将“全文”指向聚合文件，但仍称含每个 crate/npm 组件全文及版权行；§11 仍写“聚合 487 个 crate 与 npm 组件的许可全文与版权行”“M1~M4 三轮整改完毕”。鉴于上述空段及遗漏声明，聚合文件标题和这些完成状态表述仍过强。需要按实际覆盖范围改写，或补齐材料后再宣称完成。该 MINOR 不另行升级/重复计入许可 MAJOR。

## 5. 剩余人工验收清单

以下沿用既定延期，不替代先行的许可材料整改。本轮全部未运行；须在允许运行/安装的窗口用隔离数据或备份，并保留逐项证据。

1. 原 10 项：拖选、双击、双向翻译、剪贴板还原、防误触、取消、热键、报错、50 次稳定性、混合缩放双屏；#14 UIA 命中划词→浮标 ≤400ms。
2. 绑定最终发行哈希与启动日志；无控制台 [boot]/[orch]/[kb]、真实可交互时间、WorkingSet/Private，以及日志权限失败情形。
3. 中文安装向导、当前用户免管理员、默认/自选目录、快捷方式、WebView2 缺失引导、单实例、运行中升级；实际安装目录三份许可材料逐文件哈希及源码获取路径。
4. 升级/卸载与删除应用数据选项前后逐文件对比 config/CSV/JSONL/v4 索引；Python→Rust→Python 往返、旧 TM 命名续用，避免并发写同一数据集。
5. TM 完成 A→B 在途/失败→存记忆、校对配对；长领域名、窄窗、热键重启生效。
6. KB 49999+2、不可解析缓存超 50000、room=0、额度释放/incomplete；PDF/DOCX 无缓存/陈旧缓存、删除/移出/超过20MiB、非 UTF-8 边界。
7. KB 慢初始化 A→B→C、50 轮耗尽后恢复、线程创建失败；隔离保存失败，验证内存可用/磁盘失败、同目标去重，换另一有效目录再切回及重启的恢复路径。

**最终判定：FAIL。** 发行哈希与三处静态交付机制通过；M1/M2 的实际许可/归属材料仍有残余，M4 部分文档声明未闭合，M3 不重开。未把安装器脚本、历史日志或聚合文件体积当作实际安装/性能/许可完整性的独立证明。
