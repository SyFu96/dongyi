# P4 复审 Brief B（N1~N7 整改后定点复核）

你是阶段复审人，定点复核『懂译』P4 上一轮 `GATE_REVIEW_P4.md`（判定 FAIL，N1~N4 必修 + N5~N7 非阻断）的整改。**不做全量重审**：已确认解除项（交付映射表 1~8 行、P3 延续约束、热键语义等）沿用上轮结论。

## 整改映射（N 编号 → 现状）

- **N1（弹窗配置不跟随整份保存）** → `src/App.tsx` PopupView：
  - mount 的 get_config 抽为 `loadCfg`（useCallback），`useEffect(loadCfg, [loadCfg])` 挂载拉取；
  - `config:updated` 监听分支化：kind ∈ {chat,input} → 沿用事务 chip 映射（后端恒发生效 provider）；**kind 空串 → `loadCfgRef.current()` 重拉全量**（更新 provider/modelNames/cloudKeyOk/inputProvider/chatProvider）。loadCfgRef 为每帧刷新的稳定引用（监听器依赖 [] 注册）。
  - `popup:open` 处理里的重复拉取代码改为 `loadCfgRef.current()`。
- **N2（设置窗旧快照覆盖他窗写入）** → 双侧：
  - 后端 `src-tauri/src/lib.rs`：**删除整份 save_config，改 `save_config_paths`**（[ConfigPatch{path,value}]）：锁内 clone 当前内存 → serde_json IndexMut 按 path 打补丁（自动建缺失父级）→ `dongyi_core::save_config` 成功才发布 `*guard=merged` → drop 看门 → 广播 config:updated{kind:"",provider:"",theme}。设置页只提交编辑过的路径，未知字段/他窗新字段不可能被旧快照清掉。
  - 前端 SettingsView：`set()` 每次把 {path,value} 记入 `patches` Map（key=path.join("\u0001")）；保存只发 patches 条目；「放弃修改」清空 patches；**广播跟随**：clean → 重拉最新配置（impl 内清 patches），dirty → 不覆盖草稿只显示冲突提示（dirtyRef 走 ref，避免闭包捕获陈旧 state）。
- **N3（保存状态机）** → SettingsView：**切换为单调计数器判定**——`patchSeq` ref 在每次 set() 自增；save 提交时记 `seqAtSubmit=patchSeq.current`，成功后 `patchSeq.current===seqAtSubmit` → dirty=false/「已保存」；否则 dirty=true/「已保存本轮修改；保存期间的新改动尚未保存，可再次保存」。单飞 savingRef 保留，判定不再用字符串比较（上轮误报根除）。
- **N4（local_models 阻塞主线程）** → `lib.rs`：命令改 `async fn` + 短锁拷 base_url + `tauri::async_runtime::spawn_blocking(move || dongyi_llm::ollama_models(&base)).await`；**返回类型改为 Result<Vec<String>, String>**（Tauri 约束：带引用参数的 async 命令必须返回 Result）。旧同步版已删除（无重复定义）。
- **N5** → ModelSelect：空列表与不可达都显示明确提示（未取到模型/Ollama 未连接）。
- **N6** → 剪贴板进程列表改 `ProcessListInput`：本地 draft 字符串（onChange 逐字保留，非法 JSON 只置错误态不回弹不写 cfg），仅合法字符串数组才提交；外值变化（放弃/重拉）重同步。
- **N7** → useThemeSync 重构：统一 `apply/setMode` 入口 + `clearAutoListener`（先摘旧 mql 监听再换）；初始 get_config 迟到时被 `sawBroadcast` 丢弃。

## 用户实测后跟进修复（须一并验证）
- 上轮保存报 `invalid args entries... invalid type: map, expected a tuple of size 2`：因 Rust tuple ↔ 前端 map 序列化不匹配。**已修**：后端 entries 改 `#[derive(Deserialize)] struct ConfigPatch { path: Vec<String>, value: Value }`，前端无需改。
- 保存后误报「保存期间的新改动尚未保存」：N3 字符串判定误报面。**已修**：N3 计数器化（见上）。
- 需求方实测：保存成功提示正常、设置流程可用（2026-10-13）。

## 复审方法（定点）
1. 读代码核对每项（证据行号）：特别是 `provider_for` 的事务内部一致（on_kind_provider 与 save_config_paths 并存正确、共享锁）、ConfigPatch 反序列化、spawn_blocking 线程模型、patchSeq 判定无旁路（例如保存期间 abandon/重拉与 patches.clear 的交叉）、广播回环（设置窗自身收到 kind=""广播时 dirtyRef/patches 状态一致性）。
2. 跑 `cargo test --workspace --locked`（LLM 11 + core 4 + capture 1 = 16 项）与 `npm run build`（机器偶发 Node/LLVM 崩溃重试即过，不判缺陷）。
3. 上轮 N1 的两类反例（弹窗 chip 不同步 / 旧快照覆盖）用静态推理 + 可选 Node 定点执行证明已闭合。
4. **约束**：只读 + 无副作用构建/测试；禁止启动/重启 exe（运行中应用占锁）；生成报告 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P4_RE.md`。

## 产出要求
每项证据行号 + 结论；新发现 BLOCKER/MAJOR/MINOR 分级（文件:行号/原因/建议）；末列 P5 关注点（可沿用上轮）；最终判定 **PASS（P5 可开工）/ FAIL（必修清单）**。
