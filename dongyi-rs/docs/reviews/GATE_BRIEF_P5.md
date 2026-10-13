# P5 Gate 审查 Brief

你是阶段审查人，审查『懂译』Python→Rust 重构 **P5 阶段**（RAG / 术语表 / 翻译记忆 / 领域适配）。

## 背景（必读）
- 执行文档：`D:\划词小工具\Rust重构执行文档.md`（§5 架构、§7 坑清单、§10 已知限制/构建铁律、§11 阶段记录：P5 行）
- P4 闸门报告链（约束延续）：`GATE_REVIEW_P4_RE3.md`（**PASS**）与 `GATE_REVIEW_P4.md`/`GATE_REVIEW_P4_RE.md`/`GATE_REVIEW_P4_RE2.md` 的 P5 关注点：
  1) RAG/术语表/TM 兼容既有 Python 数据格式与**同一份数据文件**（`%APPDATA%\dongyi\`：glossaries\、tm\*.jsonl、kb_index\index.json v4）
  2) 新增字段遵守差异提交（save_config_paths）与未知字段保留
  3) 后台索引/文件解析**必须**走后台任务（P4 教训：Tauri 同步命令默认主线程）
  4) 配置读取/草稿编辑/广播统一代次与失败恢复；kind 缺失/空串跟随全局、失败回滚、chip 不取消在途流保持
  5) 保留输入原文、last_target retry、跨会话置顶、不抢焦点；解释惰性派发顺序不得回归
  6) 前端交付须重编 exe（frontendDist 编译期内嵌）

## P5 交付物
1. **新 crate `crates/dongyi-knowledge`**（Python domains.py/tm.py/knowledge.py 逐条移植）：
   - `domains.rs`：valid_id（1~64 [A-Za-z0-9_-]）、dedupe（大小写去重，首启用优先）、enabled、resolve_active、active、note_text（2000 截断）。**注意本轮修复**：所有函数参数 = 整个 cfg、内部取 `["domains"]`（此前误把 cfg 顶层当 domains 映射，已修）
   - `glossary.rs`：CSV（UTF-8/BOM/# 注释/末行覆盖/字段 200 截断）、词边界匹配（ASCII 词内不命中派生词）、MAX_TERMS_INJECTED=60、预算 4000、(mtime,size) 热缓存
   - `tm.rs`：`general.jsonl`/`dom_<小写id>.jsonl`（大小写共文件）、append/clear/count、Jaccard(bigram) 相似度、TOP3/0.35/1200 预算/扫码 3000 条
   - `knowledge.rs`：分块（500/1500）、BM25（k1=1.5 b=0.75 min_score=0.2 top3/2000 预算）、index.json v4 读写、增量（mtime+size 复用）、后台预热线程（Weak 自引用）、scan 跳 .git、20MB/2M 字符/5 万块上限。**裁切（已在代码注释声明）**：解析仅 txt/md/markdown/csv/json（非 UTF-8 退 lossy，无 GB18030 库）；PDF/docx 不实现；硬链接 inode 防御不实现
   - `tokenize.rs`：ASCII 词 + CJK bigram（单字保留）
   - 10 项单测（词边界/CSV 覆盖/预算/相似度/分块/BM25 命中/目录过滤/context_for 门控）
2. **注入链**：`orchestrator.rs compose_system(kind,text,base,search_ctx)` = 基础 prompt → 领域 note → 术语 → KB 片段 → TM 译例 → 联网检索；接入点：dispatch_request（translate/explain 初发）、on_search_done（explain/chat 重组）、on_chat_ask、on_input_ask。门控：chat 不检索 KB/TM；translate/input 的 KB 有 kb_for_translate 开关；TM 仅 translate/input
3. **TM 入口**：`on_tm_save`（原文=session.text/last_input，译文=last_results[kind]）+ 前端 footer「存记忆」按钮 + `tm:saved` 反馈；`last_results` 在 on_llm_event Finished 记录、begin_session 清
4. **学科切换**：`on_set_domain`（enabled 校验 → 候选先写盘 → 发布内存 → 广播 config:updated → KB 签名核对后台刷新）+ 弹窗顶栏下拉（通用 + enabled 列表）+ `domain:changed` 事件
5. **KB 刷新调度**：`maybe_refresh_kb`（目录并集签名比对；线程内先 Arc clone 保活；start() 首刷 + set_domain + save_config_paths 的 KbCheck 触发）
6. **设置页「06 领域」**：列表/新建（d1/d2 自动编号）/删除（ConfigPatch null 删除语义）/字段编辑（name/note/enabled/glossary_file/kb_dirs 每行一条/kb_enabled/kb_for_translate）；save_config_paths 后端支持 null=删键
7. **本轮实测修复（须复核）**：
   - domains 参数错位（上）
   - `show_settings`：P5 期间先加 `center()`（实测卡死主线程：日志 center 后无任何输出）→ 移除；曾误改 `async fn`（**Rust 内部直接调用的 command 不能 async——不 await 不执行**，导致托盘设置完全无反应）→ 已回滚同步函数 + 每次显示前 `set_size(820x620)` 自愈（枚举器曾观测设置窗被弄成 131x36 炁态）
   - 弹窗 footer 重排（学科名动态显示/按钮 nowrap/删尾注）
8. **需求方实测**：设置窗可开 ✓、设置保存落盘 ✓（log `save_config_paths entries=1 → domains.d1`）、新学科进 config ✓；学科下拉选用与「存记忆」显示待复测

## 复审方法
读代码核对每项（证据行号）+ 静态推反例；跑 `cargo test --workspace --locked` 与 `npm run build`（机器偶发 Node/LLVM 崩溃重试即过，不判缺陷）。
重点审查面：
- domains API 语义（cfg 参数约定 vs Python）与所有调用点一致性（compose_system/set_domain/maybe_refresh_kb/诊断 log）
- compose_system 的注入顺序/预算/门控与 Python `_compose_system` + `_chat_domain_context` 对照（chat 是否只 note+术语）
- TM/KB/glossary 的**数据文件格式与 Python 互操作**（同目录同文件；Python 版产生的 tm/jsonl、index.json v4、battery.csv 改动 Rust 侧能否直接消费）
- 线程纪律（refresh/preheat 是否全在后台；Weak 自引用的竞态）
- 知识库版本/统计代次（index_gen/built_gen）与 Python 语义
- TM 保存的会话取值（input 用 last_input、translate 用 text、译文取 last_results——与其他 kind 混淆/旧会话残留）
- 设置页领域编辑与 save_config_paths 的 null 删除、path 构造（["domains", id, field]）
- 本轮三处实测修复的静态闭合（show_settings 同步/自愈、footer 布局）
- 已声明裁切是否记录充分

## 约束
只读 + 无副作用构建/测试；禁止启动/重启 exe（运行中应用占锁）；报告写唯一文件 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P5.md`。

## 产出要求
每交付项证据行号 + 结论；新发现按 BLOCKER/MAJOR/MINOR 分级（文件:行号/原因/建议）；末列 P6 关注点（打包/安装/文档）；最终判定 **PASS（P6 可开工）/ FAIL（必修清单）**。
