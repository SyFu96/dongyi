# P5 复审 Brief B（B1+M1~M9 整改后定点复核）

你是阶段复审人，定点复核『懂译』P5 上轮 `GATE_REVIEW_P5.md`（FAIL：B1 BLOCKER + M1~M9 MAJOR + m1~m3 MINOR）的整改。**不做全量重审**：上轮已通过的交付项（domains API 参数修复、注入链顺序/门控、TM 入口白名单、设置 06 领域基础、三处实测修复）沿用结论。

## 整改映射（逐条给了实现方式；请核对代码证据行号）

- **B1（术语混合中文边界 UTF-8 panic）** → `crates/dongyi-knowledge/src/glossary.rs` `term_in_text`：不再 `byte+1` 切片——`find` 循环 + `chars().next().len_utf8()` 前进（永不切进多字节）；纯 CJK 分支包含即命中。单测 `混合中文术语边界失败不panic`。
- **M1（BM25 df 累加词频）** → `knowledge.rs` 新增 `build_stats(chunks)`：df 按 `tf.keys()` 每块 +1；refresh 与 preheat 共用。单测 `bm25_重复词块仍命中`（SOH SOH SOH 单块须命中）。
- **M2（set_domain 锁外事务覆盖并发配置）** → `orchestrator.rs` `on_set_domain`：整段在**同一 SharedCfg 锁内**完成「读当前→enabled 校验→候选→save_config 写盘→成功才 `*guard=cand`」；删除 `Ori.active_domain` 内存缓存，激活真源统一 `domains::resolve_active(&cfg)`（open_popup 诊断行同步改）。
- **M3（同会话新输入配旧译文入 TM）** → session 新增 `pending_source: HashMap<kind,(req_id, source)>` 与 `last_done: HashMap<kind,(source,result)>`；`bind_request` 返回 req_id，translate（dispatch_request）与 input（on_input_ask）登记快照；`on_llm_event` Finished 仅在 `pending_source.get(kind).0 == req_id` 时写 `last_done`；`on_tm_save` 只读 `last_done`（无配对→明确提示）；`begin_session` 清两表。`last_results` 已移除。
- **M4（KB 刷新乱序覆盖新目标）** → `orchestrator.rs` 新增 `KbSched{pending,inflight,done,running}` 单 worker 状态机：`maybe_refresh_kb` 判定「排队同目标/在途同目标且无排队/已完成且无在途排队」→ 否则 `pending=Some((sig,dirs))`（**替换为最新目标**）并确保单 worker；`kb_worker` 串行 take 消费 pending，完成后 `done=sig` 且 loop 续跑；spawn 失败复位 running。
- **M5（启动刷新删除 Python PDF/DOCX 片段）** → `knowledge.rs` refresh：不再预过滤扩展名——不支持后缀但**有旧记录**的文件同样进 wanted，按「未变复用 / 变化也保留旧缓存 + 日志告警」处理（禁静默删除）；无缓存的不支持类型跳过并告警。单测 `非解析类型保留缓存且额度截断`（v4 fixture 含 pdf chunk）。
- **M6（5 万块额度只在开头检查）** → 每个文件按 `room = MAX_TOTAL_CHUNKS - new_chunks.len()` 截断（复用与新解析统一），截断即 `complete=false`（下次容量释放后重解析补齐，恢复 Python 语义）。
- **M7（删除领域父子补丁复活 + null 草稿残留）** → `App.tsx` DomainEditor：`ids` 过滤 `domainsMap[id] === null`；`removeDomain` 先经 `dropPatches(prefix)` 清该领域全部后代补丁，再 `set(["domains", id], null)`（同键重设移到补丁尾部→提交顺序保证删除在后）；SettingsView 通过 prop 注入 `dropPatches`（遍历 patches Map 删 `prefix` 及 `prefix+\u0001*`）。
- **M8（CSV 多行引号 + 空白归一）** → `glossary.rs`：新 `parse_records`（跨物理行引号状态、`""` 转义，Python csv.reader 关键子集）；`normalize_text`（`\s+`→单空格 + 小写）供匹配与边界判定同口径。单测 `csv_多行引号字段`、`空白归一匹配`。
- **M9（首 read/parse 阻塞 setup 主线程）** → `knowledge.rs` `KnowledgeStore::new` 只建结构即返回，索引 read/parse 在 `kb-init` 后台线程完成后置 `init_done` 并（有数据时）预热；`search` 未就绪安全返回空；新增 `wait_init`（refresh 进入前等待，上限 ~10s）防覆盖未加载记录。
- **m1（TM 旧文件迁移）** → `tm.rs` 新增 `legacy_path`/`migrate_legacy`（general/dom_ 前缀保守跳过），load/append 前调用；`clear` 同时删旧名、删除失败返回 0。
- **m2（前后端同序）** → `domains.rs` dedupe 与 `App.tsx` computeDomains 统一为「lowercase 组内按 id 字节序取第一个启用的；组间按 id 排序」。
- **m3（preheat spawn 失败不复位）** → `schedule_preheat_arc`：`spawn(...).is_ok()` 失败即复位 `building`。
- **附带**：index.json 写盘改 tmp+replace（单 worker 串行下等效 os.replace）；`scan_files` 目录 canonicalize 身份 visited 防 junction 循环；弹窗 `loadCfg` 加请求票据（迟到 get_config 响应丢弃）；执行文档 §7 crate 描述改为「仅 txt/md/csv/json 直读，PDF/DOCX 不解析但可消费 Python 版已有索引」、§11 P5 行更新。

## 验证状态
`cargo test --workspace --locked`：31 项全绿（capture1 + core4 + knowledge15 + llm11）；`npm run build` 通过。需求方实测：设置可开、保存落盘、学科下拉（本轮修复 API 后待复测，未宣称）。

## 复审方法（定点）
读代码核对上表每项（行号）+ 上轮每个反例的复现路径是否被真正闭合；拉必要的静态推演。重点：
- B1 的所有翻边界路径（多出现位置、CJK+ASCII 混合、行首行尾）
- M1 两条构建路径（refresh/preheat 共用函数）与磁盘预热路径
- M2 与 save_config_paths/on_kind_provider 的互斥关系（同锁）与「A→B 设置保存交叉」
- M3 的配对矩阵（A 完成→B 在途→存 / B 失败→存 / 跨会话）
- M4 的 A→B→A 与逆序完成、worker 退出条件
- M5 的 v4 fixture 与「变化字段保留旧缓存」策略、M6 截断后补齐
- M7 的「新建→编辑→删除→保存」补丁序列、已有领域删除即时消失
- M8 多行 CSV/多空白；M9 的线程证据（new 不读盘）
`cargo test --workspace --locked` + `npm run build`（机器偶发 Node/LLVM 崩溃重试即过）。**只读 + 无副作用测试；禁止启动/重启 exe**。报告写 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P5_RE.md`。

## 产出
B1/M1~M9/m1~m3 逐条闭合证据（行号）；新发现分级；末列 P6 关注点；**PASS（P6 可开工）/ FAIL（必修清单）**。
