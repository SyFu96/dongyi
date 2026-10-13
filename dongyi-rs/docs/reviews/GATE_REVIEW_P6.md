# 懂译 P6 阶段审查报告

日期：2026-10-13。**最终判定：FAIL。** 当前产物哈希、体积、主要 bundle 配置及默认安装数据隔离机制通过；发行许可材料缺失、许可表不准确、P5 移交的故障行为说明缺失，以及性能验收门槛未闭合，阻止本轮放行。

## 1. 范围与方法

完整读取 GATE_BRIEF_P6.md、Rust重构执行文档.md（含 §8/§10/§11）及 GATE_REVIEW_P5.md → RE → RE2 → RE3 报告链。以 RE3 PASS 为 P5 结论，不重新打开已解除的 P5 反例。使用 env-list 技能核对环境，采用 PowerShell 只读检查、Get-FileHash、ZIP 内存流读取、PE 文件头读取、本机 Tauri CLI 2.12.2 schema 对照及源码抽查。

未启动、安装、运行、重启或终止产品 exe；未重新打包、前端构建或修改 release/target/dist；未操作运行中产品、真实用户配置、TM 或 KB。唯一写入文件为本报告。未复跑 Cargo 测试：本轮发行审查的缺口不由重复已有单测解决，沿用 P5 测试记录，不将其称为本轮测试结果。一次 Node 内联只读检查因 PowerShell 引号传递失败未执行，随后用 PowerShell 完成 schema 和 PE 核查，不计为产品失败。

以下行号为审查时磁盘文件行号。ZIP 条目列表是实际读取结果；NSIS 行为是现存生成脚本的静态证据，未执行安装器或独立解包安装器验证全部负载。

## 2. 逐项交付核对

### 2.1 产物、体积与 SHA256：通过

命令：Get-Item / Get-ChildItem；Get-FileHash -Algorithm SHA256；System.IO.Compression.ZipFile.OpenRead 后对 dongyi.exe 条目流计算 SHA256。

| 文件 | 实际字节 | MiB（字节/1048576） | SHA256 |
|---|---:|---:|---|
| target/release/dongyi-rs.exe | 7038464 | 6.71 | B16419D91E074AEBB266763458DB180E0F9566A70E19E2ED9574B90B30D55742 |
| target/release/bundle/nsis/dongyi_0.1.0_x64-setup.exe | 2457451 | 2.34 | 702625116D1A342AEBB5FF0DA887657D2001AA785F7D71350E43198E6DBE4E8E |
| release-artifacts/dongyi_0.1.0_x64-setup.exe | 2457451 | 2.34 | 702625116D1A342AEBB5FF0DA887657D2001AA785F7D71350E43198E6DBE4E8E |
| release-artifacts/dongyi_0.1.0_x64-portable.zip | 3124973 | 2.98 | 4E6E6630DAB0C721FB581DD66305B667932780341CBCE80715412110A8DAF0F4 |
| ZIP 内 dongyi.exe | 7038464 | 6.71 | B16419D91E074AEBB266763458DB180E0F9566A70E19E2ED9574B90B30D55742 |

SHA256SUMS.txt:2–4 三个值全部复算一致；安装包副本与构建目录同哈希；ZIP 内 exe 与 release 原程序同哈希。ZIP 实际仅两个条目：dongyi.exe（7038464 字节）、README.txt（1596 字节）。README.txt 可读，说明热键、数据目录、设置六组和 PDF/DOCX 裁切。

主程序 PE machine=0x8664（AMD64）；生成脚本 installer.nsi:52 的 ARCH=x64。版本配置及生成脚本均为 0.1.0。体积符合 brief，安装包小于执行文档 §9 的 15MB 门槛。

MINOR：SHA256SUMS.txt:4 将主程序标为“dongyi-rs.exe (raw binary inside portable zip as dongyi.exe)”，不是发布目录中可直接定位的标准文件名。人工验证无歧义，但通用逐行校验工具可能失败。建议只列实际发行文件，包内哈希另设注释说明。

### 2.2 bundle 配置、schema 与构建对应关系：静态核对通过，证据有限

src-tauri/tauri.conf.json:3–8 产品名、版本、beforeBuildCommand=npm run build、frontendDist=../dist；:16–30 active=true、targets=[nsis]、五个 icon 路径、SimpChinese/currentUser 均符合 brief。五个图标文件实际存在且非空。

本机 node_modules/@tauri-apps/cli/package.json:3 为 2.12.2；config.schema.json 的 BuildConfig/BundleConfig/WindowsConfig/NsisConfig/NSISInstallerMode 定义支持上述字段、类型和枚举。已逐项对照本次相关配置，未声称运行通用 JSON Schema 校验器覆盖全部 schema。生成 installer.nsi:40、52、104–105、464 分别确认 currentUser、x64、RequestExecutionLevel user、SimpChinese。

本机 schema 对 frontendDist 明确描述相对路径递归读取并内嵌二进制；src-tauri/src/lib.rs:331 的 generate_context!() 和 target/release/dongyi-rs.d:1 记录当前 dist/index.html、index-jMyL4vZ3.js、index-Ibhr6F7F.css 及后端源码依赖，与 README:55–56 的重编铁律一致。

时间交叉证据：App.tsx 15:14:03、orchestrator.rs 15:13:25、knowledge.rs 14:57:15；dist 两资产 15:45:01；release exe 15:57:51。扫描 crates、src-tauri/src、src 下 rs/tsx/ts/css，晚于 exe 的文件数为 0。没有发现明显“前端改后未重编”证据。但依赖列表与时间戳不等于可复现构建证明；未重新编译、未验证每个嵌入资源解码后的字节，也未证明桌面运行实例就是该发行 exe。

### 2.3 README、许可及源码一致性：部分通过

| 文档声明 | 源码证据及结论 |
|---|---|
| KB txt/md/markdown/csv/json，PDF/DOCX 不解析但消费缓存（README:31、37） | knowledge.rs:27、322–367 支持集合及不可解析缓存优先保留，基本一致。保留有前提：文件仍在启用扫描目录、元数据可读且不超过20MiB（:306–333）。不是无条件永久保留；文档需补前提。 |
| 额度/不完整补齐（README:38–39） | knowledge.rs:345–398 不可解析缓存全量先保留；可解析部分 saturating_sub(50000) 截断、complete=false。总量可任意超过50000，文档“略超”无代码上界支持。 |
| CSV 常用子集（README:40） | glossary.rs 的 field_started/引号状态/CR、LF、CRLF 处理与已闭合 P5 边界一致；不宣称完整标准兼容。 |
| 静默浮标与热键重启（README:41–42） | 执行文档:155–158 已获需求方接受；orchestrator.rs:301 启动构造热键，配置保存未重新注册该链，重启要求合理。静默浮标限制不重新列缺陷。 |
| 数据格式（README:19–22） | core/lib.rs:120–133 config.json 加载合并；tm.rs:29–39、84–101 general/dom_小写id JSONL、src/tgt/time；knowledge.rs:134–145、428–430 v4 files/chunks；对照 Python tm.py:58、135 及 knowledge.py:279、337–348，基本格式一致。Rust FileRec 不写 Python chunks 计数字段，沿用 P5 已确认其非消费者复用前提的结论。未做真实数据往返。 |
| GPL-3.0 LICENSE | Rust 与 Python LICENSE 均为 FB981668C18A279E285FC4D83FBA1E836CC84DD4DAA73C9697D3CFD2D8ACA6E0，字节一致；开头为 GNU GPL Version 3, 29 June 2007。通过。 |
| 主要直接依赖许可表 | 对照五个 crates/Cargo.toml、src-tauri/Cargo.toml、Cargo.lock、package.json，serde、tokio、reqwest、futures-util、url、thiserror、log、windows、Tauri/plugins、React、前端构建工具均覆盖；uiautomation 许可不准确，且列出并不存在的 global-hotkey/rdev，见 M2。 |

已允许的 UTF-8 lossy/无 GB18030 等裁切在 knowledge.rs:5–8、123–130 可见，但 README 未说明；属于用户文档欠缺，不要求本轮扩充解析实现。

### 2.4 实测与验收门槛：记录存在，但未闭合

Rust重构执行文档.md:148–150、164 记录 exe 6.71MiB、安装包2.34MiB、ZIP2.98MiB、启动到编排就绪约0.81s、WorkingSet约40MB/Private约10.6MB。体积本轮独立复算吻合；启动和内存仅为交付方既有记录，本轮禁止启动产品，未独立复测。brief 的40.1MB与文档约40MB仅是舍入差异，不列缺陷。

执行文档:141 要求“冷启动到托盘就绪≤0.5s”，而记录测的是“到编排就绪≈0.81s”。测量终点不同，不能据此直接认定托盘耗时也是0.81s，更不能认定0.5s门槛已通过；没有看到门槛变更/豁免记录。§8:130 的10用例全过也没有本轮可核验的完整逐项结果。本轮将缺口列 M4，不伪造性能或桌面结论。

### 2.5 安装、卸载、覆盖升级的数据隔离：默认机制通过

core/lib.rs:94–110 首选 APPDATA/dongyi，与 README:15 一致；APPDATA 不可用时存在 TEMP/dongyi、最终 exe目录兜底（:99–117），需避免将首选路径写成无例外承诺。

installer.nsi:504–505 默认安装路径是 LOCALAPPDATA/dongyi；:635–650 安装只复制主程序，没有配置、CSV、JSONL、index.json资源；:313 起 UPDATE 模式跳过先卸载；:763–777 卸载按主程序/卸载器删除并用非递归 RMDir 删除安装目录。:827–840 “删除应用数据”选项只在非更新模式删除 APPDATA/com.syfu96.dongyi 和 LOCALAPPDATA/com.syfu96.dongyi（BUNDLEID见:49），不是 APPDATA/dongyi。

因此默认路径下安装、覆盖升级和该卸载清理选项不主动删除共享业务目录。该结论基于生成脚本，不等于真实安装验收；用户自选目录、运行中程序占用、旧安装路径恢复及异常环境兜底仍须人工验证。业务启动会正常加载/保存共用数据，与“安装器不覆盖”是不同问题。

## 3. P5 RE3 移交事项落地

1. **恢复时延/暂停反馈：部分落地。** knowledge.rs:275–300 就绪门；orchestrator.rs:1282–1298 保留新目标、200ms轮间休眠、50次失败后暂停并保留目标。每轮约10s名义等待，暂停约509.8s或更久。只写stderr，README无暂停/恢复触发说明；无用户状态反馈证据。暂停后仍需配置保存触发KbCheck或领域切换等新检查。隔离慢初始化/线程失败实测未交付。
2. **持久化反馈：未完成交付说明。** knowledge.rs:433–444 保存失败仅stderr，返回统计不含保存成功状态；orchestrator.rs:1300–1310 仍登记done并发kb:refreshed。相同目录后续检查可能在:1236–1237提前返回，无落盘失败专门重试。前端未找到kb:refreshed消费及对应错误状态。此为P5既有策略，不重新判其为先删旧索引缺陷；P6须说明真实行为。
3. **缓存容量：文档基本说明，但“略超”不准确。** 代码仍保留不可解析缓存并继承complete，额度静态路径与P5结论一致；既有fixture没有49999+2、超额、room=0全套执行证据，不冒称完成。
4. **发行与界面：产物/依赖记录通过静态抽查。** TM 保存后端使用last_done完成对并可接收校对译文（orchestrator.rs:1131起）；源码有校对层。连续输入在途/失败时可能保存上一完成对，README仅写“req_id配对”而未明确上一完成对语义，仍需人工核验原文与译文。长领域名/窄窗未验证。
5. **迁移与发行：安装隔离及格式静态通过。** Python→Rust→Python缓存/TM实际往返未执行；不可解析缓存陈旧、超过20MiB、编码裁切等边界未充分文档化。

## 4. 新发现与必修清单

**本轮无 BLOCKER；4 项 MAJOR，另有上述哈希清单格式 MINOR。**

### M1 / MAJOR：二进制发行缺少已承诺随附的许可材料

证据：THIRD_PARTY_NOTICES.md:42–43 要求随二进制保留本文件与LICENSE；ZIP实际只有dongyi.exe/README.txt；tauri.conf.json:16–31无resources/licenseFile；installer.nsi:41 LICENSE为空、:647–648资源复制为空；release-artifacts目录也无这两份文件。

原因：源码根目录存在许可文档不代表接收二进制的用户拿到了文档。当前发行与自身交付声明矛盾。

必修：由实施方在获准的后续发行构建中将LICENSE和THIRD_PARTY_NOTICES实际随安装版、绿色版交付，补足所选第三方许可要求的文本/声明，并明确对应版本源码获取方式。本报告不作法律合规完备性背书。审查人遵守禁止打包要求，不修改发行物。

### M2 / MAJOR：第三方许可表将 Apache-only 组件误写为双许可

证据：THIRD_PARTY_NOTICES.md:27 写 uiautomation “MIT或Apache-2.0”；Cargo.lock:4340起锁定uiautomation 0.25.1；本机registry该包Cargo.toml:36明确license="Apache-2.0"（derive包也为Apache-2.0）。:28 的global-hotkey/rdev均不在当前直接依赖或Cargo.lock，实际钩子由windows实现。

必修：uiautomation改为Apache-2.0，按实际所选许可随附材料；删除占位依赖行或替换为真实实现说明。以锁定版本真实元数据复核表，不以Cargo.lock当作许可文本（锁文件主要记录版本/来源/校验值）。

### M3 / MAJOR：故障与缓存边界未写入用户文档，P5移交要求未闭合

证据：README.md:35–42；knowledge.rs:123–130、318–320、345–367、433–444；orchestrator.rs:1236–1237、1282–1310；GATE_REVIEW_P5_RE3.md末尾关注点1–3、5。

原因：用户无法从交付文档获知初始化期间检索返回空、有限重试耗尽暂停及再触发方式、磁盘保存失败但内存仍成功且不专门重试、源文件改变后仍可能使用旧PDF/DOCX内容、20MiB/编码边界。README“略超上限”未反映不可解析缓存没有总量上界。当前stderr与普通完成事件不足以证明桌面用户可识别失败。

必修：README及绿色版说明明确上述行为、可操作的诊断/恢复方法、保留条件和无界超额语义；在交付记录中区分内存/磁盘成功。若产品宣称已有用户可见故障反馈或自动保存重试，需补实际实现和证据，否则如实列为已知限制。此项不要求重开已放行P5算法。

### M4 / MAJOR：冷启动验收及用例完成状态缺少闭合证据

证据：Rust重构执行文档.md:130、141、148–150、164。

原因：现有约0.81s记录的测量终点与≤0.5s托盘就绪标准不相同，无同口径达标证据或获准门槛调整；10用例全过没有完整可核验记录。禁止运行产品意味着本轮不能代补。

必修：实施方/需求方在允许运行的窗口提供同口径启动结果和既定用例状态；如接受0.81s及延期人工项目，明确登记门槛调整/豁免与验收范围，更新阶段状态，不能把构建成功等同于性能及全部用例通过。未完成项目应逐项标“待人工验收”。

## 5. 发布前剩余人工验收项

以下须由需求方在允许启动/安装的窗口执行，测试前备份数据或使用隔离账户/目录；本轮均未执行。

- 中文安装向导、当前用户免管理员、默认/自选路径、开始菜单与桌面快捷方式、WebView2缺失时引导、安装后启动与单实例；覆盖升级时运行中产品占用的处理。
- 升级/卸载（含“删除应用数据”选项）前后，config、CSV、JSONL、v4索引逐文件比对；现行与旧TM命名迁移；Python→Rust→Python往返，避免同时写同一数据集。
- 冷启动到托盘就绪同口径计时、WorkingSet/Private稳态；10用例逐项记录，包括混合DPI、剪贴板还原、取消、50次稳定性等，已获准限制明确排除。
- 学科下拉、长领域名与窄窗；A完成→B在途/失败→存记忆、校对原文/译文及上一完成对语义；热键修改重启生效。
- 隔离KB fixture：49999+2、不可解析缓存超过50000、room=0、容量释放、incomplete不升级；陈旧PDF/DOCX及>20MiB源文件；非UTF-8读取结果。
- 慢初始化A→B→C、50次耗尽后同目标恢复、线程创建失败；隔离保存失败，确认用户能识别内存成功/磁盘失败及真实恢复步骤。
- 修正发行后重查安装版/ZIP中的许可材料、最终SHA256及版本对应关系。

**最终判定：FAIL。M1–M4闭合后再做P6定点复审；当前哈希与默认安装数据隔离核对通过，不等于可直接发布。**