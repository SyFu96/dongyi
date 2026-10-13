# 懂译 P5 阶段审查报告

日期：2026-10-13。**最终判定：FAIL（下列必修项解除前，P6 不可开工）。**

指定测试及前端构建均通过，但存在 1 项 BLOCKER、9 项 MAJOR。正常路径日志、需求方实测与现有单测不能排除这些反例。

## 1. 范围、方法与证据边界

完整读取 `GATE_BRIEF_P5.md`、`GATE_REVIEW_P4.md`、`GATE_REVIEW_P4_RE.md`、`GATE_REVIEW_P4_RE2.md`、`GATE_REVIEW_P4_RE3.md` 及父目录 `Rust重构执行文档.md`（含 §5/§7/§10/§11）。P4 以 RE3 PASS 为准，历史已解除问题不重新作为失败项。对照 Python `划词小工具/domains.py`、`tm.py`、`knowledge.py` 和 `app.py` 的相关调用、组装与调度实现，核对当前 Rust/React 源码并静态推导反例。下列行号对应审查时磁盘源码。

未启动、重启或替换产品 exe，未调用真实 IPC、模型服务，未修改真实配置/知识库/记忆或业务源码。唯一新增文档为本报告；dist/target 为 brief 指定构建测试的正常产物。Cargo 启动测试程序，不是产品实例。未独立复验桌面交互，也未证明运行中 exe 与当前源码一致；不把静态反例称为桌面实测。

| 验证 | 实际结果 |
|---|---|
| `cargo test --workspace --locked` | 首次通过，退出码 0，编译 42.98s；capture 1、core 4、knowledge 10、LLM 11，共 26 项通过；壳层、trigger、doc-tests 为 0 项。 |
| `npm run build` | 首次通过，退出码 0；tsc + Vite 8.3.4，19 modules，Vite 19.99s。插件耗时提示不是缺陷。 |
| Python 数据互操作 | 源码格式、路径、读取/刷新生命周期对照；未向真实数据文件写入，未执行 Python 应用。TM 现行 JSONL 基本兼容；KB 初读兼容不代表启动刷新后仍兼容。 |

现有 10 项 knowledge 测试未覆盖重复词 BM25、中文混合术语失败分支、Python PDF/DOCX 缓存续用、5 万块临界值、领域事务并发、刷新目标乱序、同会话输入错配或父子配置补丁冲突。

## 2. 交付项逐项核对

| 交付项 | 证据行号、结论 |
|---|---|
| 1a domains API | `crates/dongyi-knowledge/src/domains.rs:7–10` id 校验；`:55–78` 大小写分组/启用优先/排序；`:83–108` enabled/resolve_active/active；`:48–49` note 2000 字符。cfg 入口内部取 domains；编排 `:186、203、902、1137、1179` 均传整份 cfg，**本轮参数错位修复通过**。注意 Python `dedupe_domains` 自身接收 domains 映射，enabled/resolve_active 接整份 cfg；Rust wrapper 约定一致即可，无须机械同签名。 |
| 1b glossary | `glossary.rs:53–96` BOM/注释/末行覆盖/译文备注 200 字符；`:134–172` 长词优先、60 条/4000 正文字符预算；`:186–222` 同数据目录、mtime+size 缓存。原文不截断与 Python 一致。**部分通过，词边界 panic、空白匹配与多行 CSV 不通过（B1/M8）**。 |
| 1c TM | `tm.rs:29–39、62–98、101–175` 现行 general/dom_小写文件、src/tgt/time JSONL、追加/清空/count、Jaccard、TOP3/0.35/1200、最近 3000 条及 600 字符句对过滤。**现行格式与检索常量通过**；并非完整迁移 Python 旧文件升级逻辑（m1），入口配对见 M3。3000 仅限制评分条数，加载仍读整份文件，与 Python 相同。 |
| 1d KB/分词 | `knowledge.rs:22–27、68–130` 分块与解析；`:154–191、244–251、302–305` v4 读取/mtime+size 复用/写入；`:315–375、455–496` 检索/目录门控/预算；`tokenize.rs:5–47` ASCII 词及 CJK bigram/单字。**框架实现，BM25/额度/互操作不通过（M1/M5/M6）**。 |
| 1e 10 项单测 | `glossary.rs:226–274` 4 项；`tm.rs:186–219` 2 项；`knowledge.rs:499–563` 4 项。**数量及实际执行通过**，不据此认定未覆盖反例正确。预算统计不计标题和连接换行，沿用 Python，同口径不列新增缺陷。 |
| 2 注入链 | 编排 `orchestrator.rs:183–211` 顺序为 base→note→glossary→KB→TM→联网；接入 `:455、561、570、1010、1046`。Python `app.py:726–766` 对照一致；KB `context_for:457–468` chat 跳过、translate/input 开关；TM 仅 translate/input，通用模式亦可用。**顺序与门控通过**；KB 实际命中受 M1/M4/M5 影响。 |
| 3 TM 入口 | 编排 `:1102–1131` kind 白名单、input last_input/translate text、last_results[kind]；`:1290–1302` 请求身份校验后 Finished 记录；`:596–606` 新会话清空。前端 `App.tsx:386–388、657–663` 按钮/反馈，壳层 `lib.rs:190–193` 事件投递。**跨 kind/新会话基本隔离通过，同会话连续输入不通过（M3）**。 |
| 4 学科切换 | 编排 `:1136–1171` enabled 校验/落盘/内存/事件；前端 `:54–71、227–228、583–593` enabled 下拉与通用选项；壳层 `:196–199` 接入。**事务不通过（M2）**。domain:changed 发出但前端未监听；正常同步依赖 config:updated→get_config，不应把事件发出当作前端消费证明。 |
| 5 KB 刷新 | 编排 `:334、377、1176–1212` 首刷/事件/目录并集/线程；壳层 `:101` 保存触发 KbCheck。Arc 在 spawn 前 clone，生命周期有效，和 brief 所述线程内 clone 位置不同但保活目的成立。**刷新/预热计算有后台线程，目标调度与初始化线程不通过（M4/M9）**。 |
| 6 设置 06 领域/null | 前端 `:1012、1240、1429–1555` 列表/new dN/delete/name/note/enabled/glossary/kb_dirs/kb_enabled（后续 kb_for_translate 表单）；`:1441` 叶路径；后端 `lib.rs:68–101` 当前配置差异合并、null 删除、写盘成功发布。P4 的 ticket/seq/失败保留在 `App.tsx:1030–1103` 保持。**父子补丁与删除草稿不通过（M7）**。 |
| 7 三处实测修复 | domains 见 1a；`lib.rs:141–148、358` show_settings 为同步、无 center、每次 set_size(820,620)，托盘直接调用有效；前端 `:646–668` 动态领域名/nowrap 按钮/移除尾注。**静态修复基本闭合**；set_size 错误被忽略，不能称强制恢复必然成功；超长领域名/多个 shrink-0 在窄窗仍可能裁按钮，列 P6 视觉核验。 |
| 8 需求方实测 | 接受 brief 的设置打开、保存落盘、新学科进入 config 记录。下拉选用/存记忆仍待桌面复测；本轮因禁止启动 exe 不补测、不伪称完成。正常路径日志不排除 M2/M3/M7。 |

P4 延续：provider 缺失/空串跟随全局仍见编排 `:160–169`，kind 事务原锁内提交逻辑保持 `:1215` 起且未新增取消在途流；解释惰性 `:963–978` 未提前 insert；输入原文 `App.tsx:917–925` 保留，last_target `orchestrator.rs:1034–1035、1076–1079` retry 回放，begin_session 不清 pinned；默认无焦点窗口 `lib.rs:319–320`、交互标签动态焦点 `orchestrator.rs:963–965` 保持。新增领域切换破坏了原统一配置事务（M2），不能整体宣称延续约束全通过。

## 3. 新发现与必修建议

### B1 / BLOCKER：混合中文术语边界失败会触发 UTF-8 非法切片，release 可终止产品

**证据：** `glossary.rs:118–125`，`Cargo.toml:15`（release panic=abort）。

静态确定性反例：term=`锂ion`，text=`a锂ion`。find 返回 byte start=1，前一字节 a 是 ASCII，边界失败；随后 `lowered_text[start+1..]` 从 byte 2 开始，处于“锂”的 UTF-8 编码内部，Rust 字符串切片 panic。该函数直接在编排线程组装 prompt 时调用；debug 会使编排线程退出，release abort 会终止进程。无需损坏数据，仅合法 CSV 与正常输入即可触发。

**建议：** 使用 char 边界或 match_indices 遍历，禁止任意 byte +1 切片；定点覆盖混合中文术语前后边界失败及多次出现。

### M1 / MAJOR：BM25 df 累加词频，重复词反而被过滤

**证据：** `knowledge.rs:281–284、428–431、361–367`；Python `knowledge.py:254–262`。

refresh 和 preheat 都 `df += n`，正确值是每个包含该词的块 +1。单块文本 `SOH SOH SOH`、查询 SOH：Rust N=1、df=3，idf=ln(1+(1-3+0.5)/(3+0.5))=ln(4/7)<0，score 负数低于 0.2，精确命中返回空；Python df=1，idf=ln(4/3)>0，能命中。当前测试每块目标词只出现一次，未暴露错误。

**建议：** 两处统一按 tf.keys() 加 1，最好共享统计函数；定点验证重复词及磁盘预热/refresh 两条路径。

### M2 / MAJOR：set_domain 锁外整份候选写盘/发布，覆盖并发成功配置

**证据：** 编排 `:1147–1157`；壳层 `lib.rs:68–91`。

`:1147` lock 后立即 clone，语句结束释放锁，save_config 在锁外；`:1157` 再次加锁整份替换。顺序可为：set_domain 取得旧 cfg→设置保存 theme=new 成功→set_domain 将旧 cfg+active_domain 写盘并发布，theme 和其他最新字段丢失。还可能写盘/内存交叉造成二者不一致。不同于串行编排事件，save_config_paths 在 Tauri 命令线程独立执行，确有并发来源。active_domain 独立缓存也未随设置保存更新，`:1142` 可能错误提前返回。

**建议：** 与 kind 事务一样，在同一 SharedCfg 锁内基于当前值校验/候选/写盘/发布；以 cfg 为唯一激活真源，取消或同步额外缓存，失败反馈前端。覆盖设置保存与领域切换交叉。

### M3 / MAJOR：同会话新输入可与上次完成译文配对入 TM

**证据：** 编排 `:1033–1035、1109–1112、1296–1302`；前端 `:657–663`。

输入 A 完成，last_results.input=译文 A；提交 B 立即把 last_input 改为 B，却不清除/绑定旧结果。B 流式输出出现 meta.text 后按钮已可点击，或者 B 失败留下部分文本；on_tm_save 读取 B + 译文 A，写入错误句对。新会话清空只能防跨会话，req_id 门控只能防迟到事件，均不能证明 last_input 与 last_results 来自同一次完成。

**建议：** 保存 Finished 对应的 source/result/request 快照，或新请求清可保存结果并要求完成状态，保存时核对请求身份；验证 A 完成→B 在途/失败→存记忆。

### M4 / MAJOR：KB 刷新没有 inflight/pending 或目标代次，旧目录最后覆盖新目标

**证据：** 编排 `:1187–1212`；KB `:267–305`；Python `app.py:808–867`。

签名只记录已完成目标，每次 changed 独立 spawn。A 目录刷新慢，配置改 B 后 B 刷新先完成，随后 A 发布索引并把签名改回 A；当前配置是 B，但全局索引最终是 A，B 的目录过滤查不到内容。另一个明确反例：done=A，B 在途，配置改回 A，changed=false 而跳过；B 最后完成，配置 A/索引 B。index_gen 只保证统计属于所发布索引，不能保证发布的是最新配置目标。并发 fs::write 同一个文件还无串行/原子落盘保证。

**建议：** 移植 Python 的单 worker+pending/inflight/done 目标状态机，或有效目标代次校验并串行持久化；不能仅给 kb_sig 加锁。定点覆盖 A→B→A 和逆序完成。

### M5 / MAJOR：启动刷新删除 Python 已生成的 PDF/DOCX 片段，违背声明的直接消费

**证据：** crate `lib.rs:6–7`；KB `knowledge.rs:154–168、203–209、244–259、288–305`；首刷编排 `:334`。

v4 初读能读 Python chunks，但 refresh 在考察旧缓存之前先过滤不在 SUPPORTED_EXTS 的文件；PDF/DOCX 从 wanted 消失，发布和保存时所有对应记录/片段被删除。因启动自动首刷，已有 Python PDF/DOCX 索引只有短暂存活，不能实现“Python 版索引生成后本 crate 直接消费”。本项不是要求实现 PDF 解析，而是要求已声明不解析的类型仍可安全消费原索引，并避免破坏共用文件。

**建议：** 对现存、目录允许且 stamp 未变的 PDF/DOCX 保留 Python 缓存；变化但无法解析时明确策略/提示，禁止静默当删除。用含 txt+pdf+docx 的 v4 fixture 验证启动刷新后的记录与检索。

### M6 / MAJOR：5 万块仅在文件开始检查，单文件可越界且永远 complete=true

**证据：** KB `:241–259`；Python `knowledge.py:421–447`。

已有 49,999 块，下一文件产生 1,334 块（2M 字符以内的长段即可），Rust 全部 push 得到 51,333，超过上限。复用分块也整批 push。没有 remaining room 裁切，FileRec 总是 complete=true，和 Python 对额度截断置 complete=false、空间释放后补齐的语义不同。

**建议：** 复用和新解析统一按 remaining room 截断并记录 complete；验证临界值及释放容量后补齐。FileRec 写盘还省略 Python 的 chunks 数字段，应恢复格式或明确证明所有消费者不依赖它。

### M7 / MAJOR：父子补丁冲突可使删除领域复活，null 草稿还留在列表

**证据：** `App.tsx:995–1003、1074–1086、1436–1458`；后端 `lib.rs:77–87`。

新建 d1 生成父路径补丁→编辑 name 生成子路径补丁→删除 d1 将父路径 value 改 null。Map 更新原键不改变插入位置，所以提交顺序是父删除→子 name；后端子路径自动建父级，d1 被重新创建。已有领域删除后 `setIn` 只写 null，ids 只检查 key 不过滤 null，领域仍在草稿列表并可继续编辑，进一步产生父子冲突。序号保护同一路径新编辑不能解决祖先/后代关系。

**建议：** 删除在前端真正移除 key；父路径替换/删除时消除对应后代补丁，子编辑要合并父补丁或规范化路径集。定点核验新建→编辑→删除→保存不落盘任何该领域，已有领域删除即时退出列表。

### M8 / MAJOR：合法 Python CSV 与多词术语匹配未对齐

**证据：** `glossary.rs:22–48、56–57、111–116`；Python `domains.py` 的 csv.reader 与 `_term_in_text`。

load 按物理行 parse_row，无跨行引号状态。例如 `SOH,"state\nof health",note` 是 Python 可读的一条合法 CSV，Rust 把第一行解析成 SOH→state，第二行误解/忽略，译法损坏。匹配声明空白归一化，实际 joined 仅用单空格；术语 `state of health` 对文本 `state\tof\nhealth` 或连续空格无法命中，而 Python 使用 `\s+` 能命中。两项都未在允许裁切中声明。

**建议：** 使用可靠 CSV record 解析，并实现任意非空空白序列匹配；保留现行预算与词边界。分别用带引号多行译文及多种空白 fixture 对照。

### M9 / MAJOR：首次 stores 初始化仍在 setup 主线程读/解析整个 index.json

**证据：** 壳层 `lib.rs:325–327`；编排 `:334、1198–1203、142–147`；KB `:158–167`。

setup 直接调用 start，start 首次 maybe_refresh_kb，在 spawn refresh 之前先 ensure_stores；KnowledgeStore::new 同步 read_to_string+JSON 反序列化整个索引。故 refresh/preheat 的后台计算没有覆盖索引文件初读与解析，大型已有索引仍阻塞启动/UI 线程，违背 brief 文件解析后台要求。不能因后续存在 thread::spawn 就认定全链路后台。

**建议：** stores 首次读取/反序列化移入后台初始化任务，完成后发布 Arc；启动阶段仅注册调度，检索未就绪安全返回空。用调用链/线程证据确认初始化也离开 setup。

## 4. 非阻断事项、裁切记录与证据限制

- **m1 / MINOR：TM 旧文件迁移缺失。** `tm.rs:62–78、142–155` 未移植 Python `tm.py:_legacy_path/_migrate_legacy`。只有旧 battery.jsonl 的用户升级后 Rust 看不到旧记忆，首次写 dom_battery.jsonl 后还会遮蔽 Python 后续自动迁移。建议补无歧义旧文件迁移，或明确升级要求。clear 删除失败仍返回 removed（`:89–92`），应对齐 Python 失败返回 0，避免误报。
- **m2 / MINOR：去重“第一个”顺序未完全对齐。** Rust `domains.rs:60` 遍历默认 serde_json 映射顺序；未启用 preserve_order，而 Python 保留 JSON 插入顺序。两个仅大小写不同且均启用的键，Python keeper 可与 Rust 不同，active_domain 会回退通用。建议明确定义统一顺序并让前后端共用；现有 domains/tokenize 没有独立单测。
- **m3 / MINOR：预热线程创建失败不复位 building。** KB `:402–446` CAS=true 后 spawn 结果被 `.ok()` 忽略，spawn 失败时永远 building=true，后续 search 不能再调度。建议失败时复位并记录可恢复错误；Weak 在创建线程前 upgrade 保活，正常路径生命周期和 `:437` index_gen 检查正确。
- 已允许的 txt/md/markdown/csv/json、UTF-8 lossy、无 GB18030、无 PDF/docx 解析、无 inode 防御，代码 `knowledge.rs:5–8` 明确记录；不因这些已允许裁切本身判 FAIL。M5 是裁切实现与“消费已有索引”承诺冲突。该注释还提到 symlink 防御裁切，实际扫描 `:379–390` 跟随目录且无 visited，目录 junction/链接循环的风险应在用户文档明确，并优先避免跟随循环。
- 直接 fs::write index.json 的失败被忽略（`:302–305`），不同于 Python 临时文件替换方式；共享索引需要原子写与失败可见性，建议随 M4 修复。未制造断电或读写交叉实测。
- 执行文档 §11 P5 仍标“未开工”，§7 crate 描述仍宣称 PDF/DOCX 解析，和当前交付状态/裁切不一致；应由实施方修正文档，本轮按唯一产出约束未改。
- 保存中忽略广播仍见 `App.tsx:1056–1058`，沿用 P4 的已知边界：无后续广播时不保证未编辑字段显示最终收敛。不重新将该历史边界作为本轮独立阻断项；P5 领域列表需要明确重拉策略。弹窗 get_config 回调 `:215–228` 也未设置请求票据，快速连续更新的迟到读取可能回退显示，应纳入配置同步核验。

## 5. 放行必修清单与 P6 关注点

**FAIL。** 必须解除 B1 与 M1–M9：安全术语边界、正确 BM25 df、领域锁内事务、TM 同请求配对、KB 最新目标串行调度、Python 非解析文档缓存保留、严格总块额度、删除与父子补丁归一化、合法 CSV/空白匹配、后台索引初始化。复审采用上述明确反例的定点证据及改动对应必要构建，无需重复不相关测试或重开静默划词浮标弃审事项。

P6 关注点：

1. 打包前先前端 build，再重编产品 exe；frontendDist 编译期内嵌，记录源码、dist、exe 的对应关系。在用户授权的运行窗口完成学科下拉、存记忆、连续输入/失败、长领域名及窄窗 footer 验收；本轮未替换运行实例。
2. 安装/升级沿用 `%APPDATA%\\dongyi`，NSIS/zip 不覆盖用户 config、CSV、JSONL、v4 索引；覆盖现行与旧 TM 文件升级，以及 Python→Rust→Python 续用。测试使用隔离数据，不破坏真实资料。
3. README/阶段记录/第三方许可与已允许裁切一致，明确解析格式、编码、链接扫描、KB 未就绪/刷新失败策略；不要宣称未实现的 PDF/DOCX 解析或无条件缓存兼容。
4. 按执行文档准备 NSIS+zip+SHA256、体积/冷启动/内存与既定验收用例证据；混合 DPI、PDF/终端取词及富格式剪贴板沿用前阶段边界。正常实测不能替代本轮并发与数据兼容反例验证。
