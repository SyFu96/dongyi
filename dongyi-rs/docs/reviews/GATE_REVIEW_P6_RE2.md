# P6-C 定点复审报告

日期：2026-10-13。**最终判定：FAIL。** M1 的源码交付渠道闭合，但第三方许可材料仍缺失，M1/M2 尚未整体闭合；M3 闭合；M4 的门槛和计时边界闭合，最终产物数值及完成状态描述仍需同步。

## 范围与方法

仅核验 GATE_REVIEW_P6_RE.md 的残余及本轮整改明细。使用 env-list 技能、PowerShell 文件读取、SHA256 复算、ZIP 内存流逐文件比对，并查阅官方许可文本。仅新增本报告；未启动、安装任何产品 exe，未构建、重新打包、安装依赖、修改发行文件或用户数据，未复跑无关测试。沿用 P5 RE3 放行与既定人工验收延期。

安装器材料证据限于 bundle.resources、现存 installer.nsi、资源副本及发行/构建安装器同哈希；未独立解包安装器，实际安装后的文件留待人工验收。源码一致性不等于可复现构建或源码与二进制的独立证明。

## 1. 发行物与 SHA256

| 发行文件（release-artifacts/） | 实际字节 | SHA256 |
|---|---:|---|
| dongyi_0.1.0_x64-setup.exe | 2,473,015 | F804E764C1A3C9D2C012EE303F2AF976BCAB6A77F2704050C89388B9943B53AB |
| dongyi_0.1.0_x64-portable.zip | 3,145,076 | 9D85B81C0094CC4285F211E889EE75EAA56F2F1B8B06057C9D8A84DE0FEDB701 |
| dongyi-0.1.0-source.zip | 577,790 | 3B8CB96F0FA972DB3EB96D73875211E4EB58AAEFFA2FAAA85DB7334DD775AAAB |

均与用户给定值及 SHA256SUMS.txt 一致。清单三个非注释行均指向实际发行文件，包内程序哈希列为注释，**原 MINOR 闭合**。发行 setup 与 target/release/bundle/nsis 的文件同哈希。

绿色 ZIP 五个根目录文件：dongyi.exe（7,044,608 B）、README.txt（1,762 B）、README.md（6,677 B）、LICENSE（34,674 B）、THIRD_PARTY_NOTICES.md（5,097 B）。程序与 target/release/dongyi-rs.exe 同哈希：A7F4346E6E4A17972FBE588F6A79429B9BBC59FD3D0F6EBB1C47EF6016EB219B。README.md 与工作区同哈希：2A91F93965B4B43FF6E6C87B4FB4B499C8E74B363F5764105C56A563466579A5；LICENSE 与 notices 均与工作区及 target/release 资源副本同哈希，分别为 FB981668C18A279E285FC4D83FBA1E836CC84DD4DAA73C9697D3CFD2D8ACA6E0、3C45FE9D04BFDF8CD552B3EF4717E928EA60519D3E4A5636417C055A2223DDA4。

## 2. M1：源码渠道闭合，许可材料仍 FAIL

**源码归档核验通过。** 实际目录为 release-artifacts（整改明细中的 elease-artifacts 是笔误）。ZIP 包含 dongyi-rs 根前缀下的 98 个文件，规范化路径后逐文件 SHA256 均与当前工作区一致。src/、crates/、src-tauri/、public/、dist/ 全部当前文件，以及 Cargo.toml/Cargo.lock、package.json/package-lock.json、前端配置、图标、README 和许可材料均存在；没有 target 条目。版本配置为 0.1.0，含新增日志重定向源码。THIRD_PARTY_NOTICES.md:100–102 指定该对应版本归档，可作为本轮交付集合内的实际获取方式。发布时须将该归档与二进制一同提供；“向作者索取（发布说明中的联系方式）”仍无具体联系人，不能单独作为有效渠道，但不再阻断已有归档交付路径。本轮未验证外部发布下载页面。

**MAJOR 残余（延续 M1/M2，不重复计数）：** THIRD_PARTY_NOTICES.md:63–85 并非 Apache-2.0 全文，只含简述、链接和附录声明模板，缺少第1～9节。:66–67 声称源码归档内包含全文，但归档内 notices 与当前文件完全一致，同样缺失；没有独立的第三方 LICENSE/NOTICE 文件补足。官方文本明确区分完整条款与附录，第4节要求交付许可副本。[Apache 官方许可全文](https://www.apache.org/licenses/LICENSE-2.0.txt)

MIT 段落 :39–61 已有授权及免责条款，但没有对应组件版权声明。例如实际随程序使用的 React，其 node_modules/react/LICENSE:3 有 Meta Platforms 版权行，随包 notices 未保留。通用许可模板不能替代组件应随附的版权/归属声明；官方 MIT 文本同时包含版权栏并要求保留声明。[OSI MIT 文本](https://opensource.org/license/mit)

闭合要求：补齐 Apache-2.0 真正全文，保留实际分发组件所需版权声明和上游 NOTICE（若有），按所选许可核对主要运行组件；同步源码归档、绿色包和安装资源。上游全文链接或“未列组件可自行获取”的承诺不能补足当前随附材料缺口。本结论针对既定交付证据，不宣称完成全依赖法律合规审计。

## 3. M2：元数据与交付机制通过，材料仍未闭合

本机 registry 中 uiautomation-0.25.1/Cargo.toml:36、uiautomation_derive-0.7.9/Cargo.toml:30 均为 Apache-2.0，与 notices:27 一致。notices:30–31 的 WH_MOUSE_LL/WH_KEYBOARD_LL 与 crates/dongyi-trigger/src/lib.rs:163、167 一致，RegisterHotKey 误述已清除。

notices:103 明确随安装目录与 ZIP 交付；tauri.conf.json:19–22 映射 LICENSE/notices；installer.nsi:649–650 复制两文件，:769–770 删除；绿色包与资源副本核验通过。**元数据、钩子描述、随附机制闭合，但随附内容缺口与 M1 相同，M2 整项仍 FAIL。**

## 4. M3：闭合（运行验收保留）

README.md:40–43 明确四项前提：源文件仍在启用领域的扫描目录、元数据可读、大小≤20 MiB、索引已有片段；与 knowledge.rs:306–365 的 wanted 扫描及旧块保留路径一致。:72–73 区分无缓存完全不出现与有缓存但源文件已更新；绿色 ZIP 已随附逐字节一致的完整 README.md，故旧 README.txt 简版不再形成交付缺口。

README.md:55–65 给出 %APPDATA%\\dongyi\\app.log，当前用户正常 APPDATA 对应 C:\\Users\\11054\\AppData\\Roaming\\dongyi\\app.log；保存失败解除权限/占用后换另一有效目录再切回或重启，明确没有自动保存重试。与 orchestrator.rs:1236 的完成签名去重、:1304 的 done 标记相符。

lib.rs:234 在启动早期调用 redirect_stderr_to_log；:345–364 以 append 打开日志，用 SetStdHandle(STD_ERROR_HANDLE) 设置句柄并保持存活；Cargo.toml 启用 Win32_System_Console。现存 app.log（187 B，最后写入 2026-10-13 16:40:21）可读到 [boot] ready in 728ms、[orch] kb refreshed 及 [llm-stream] 行；未见独立 [kb] 行，未据此宣称所有故障日志已实测。日志没有发行哈希关联，不能证明来自最终文件，也不能独立证明“无控制台启动”条件。

边界：data_dir() 可在 APPDATA 不可写时回退；打开日志或 SetStdHandle 失败也会静默返回。因此该日志位置是正常环境下的诊断入口，不能保证任何权限环境必定产生日志。本轮静态整改通过，恢复及无控制台日志实际行为留待授权运行窗口验证。

## 5. M4：门槛/口径通过，文档一致性部分未闭合

执行文档 §1:19 与 §9:141、150 已统一≤1s并登记确认日期；§9:150、§10:163 收窄为 run()→setup末尾的构建/启动调用返回，未冒充前端渲染或全链就绪。615ms 为历史交付记录，现存日志为728ms，两者都低于1s；本轮没有独立计时。完整10项和 #14 仍明确待人工验收，延期状态有效。

**MINOR 残余：** 执行文档 §9:149、§10:161–162 仍写旧 setup 2,470,062 B、exe 7,040,000 B，实际是2,473,015 B和7,044,608 B；绿色包当前3,145,076 B，按MiB保留两位是3.00而非2.99。§11:179 同样沿用2.99 MiB，并误称“随附 MIT/Apache-2.0 全文”“M1~M4两轮整改完毕”。615~728ms目前仅在§11汇总，§9/§10需明确历史615与新记录728的出处及产物关联边界。该项不单独升级MAJOR，但“全部文档已同步”的整改声明不成立；不能用上版实测字节数代表本版最终发行物。

## 6. 必修与剩余人工验收

先补齐 M1/M2 的实际许可文本与声明，并同步各交付副本；清理 M4 数值及“全文/整改完毕”的不实描述，再核验最终发行文件哈希。本轮不代为修改或打包。

以下仍未在本轮执行，须在允许运行/安装的窗口，以隔离数据或备份进行并留逐项证据：

1. 原10项：拖选、双击、双向翻译、剪贴板还原、防误触、取消、热键、报错、50次稳定性、混合缩放双屏；#14 UIA命中时划词→浮标≤400ms。
2. 将最终发行哈希与启动日志绑定；验证无控制台启动的 [boot]/[orch]/[kb] 日志、真实可交互时间、WorkingSet/Private，记录日志权限失败情形。
3. 中文安装向导、当前用户免管理员、默认/自选目录、快捷方式、WebView2缺失引导、单实例、运行中升级；实际安装目录中的最终 LICENSE/notices 与源码获取路径。
4. 升级/卸载及删除应用数据选项前后，逐文件比对config/CSV/JSONL/v4索引；Python→Rust→Python往返、旧TM命名续用，避免并发写同一数据集。
5. TM完成A→B在途/失败→存记忆及校对内容配对；长领域名、窄窗、热键重启生效。
6. KB额度49999+2、不可解析缓存超50000、room=0、额度释放/incomplete；PDF/DOCX无缓存/陈旧缓存、删除/移出目录/超过20MiB、非UTF-8边界。
7. KB慢初始化A→B→C、50轮耗尽后恢复、线程创建失败；隔离保存失败，验证内存可用/磁盘失败、同目标去重，以及换另一有效目录再切回和重启的实际恢复路径。

**最终判定：FAIL。主要阻断仍是 M1/M2 的第三方许可随附材料；M3 已闭合，人工验收延期不能代替许可交付整改。**
