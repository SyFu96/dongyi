# P3 最终复审 Brief B（F1~F8 整改后）

你是阶段复审人，复核『懂译』Python→Rust 重构 **P3 阶段**在上一轮最终复审后的整改。

## 前置报告（必读）
1. `D:\划词小工具\dongyi-rs\GATE_BRIEF_P3_FINAL.md`（上一轮 brief，含 RR1~RR7 映射约束）
2. `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3_FINAL.md`（上一轮 FAIL 报告，**本轮整改对象 F1~F8**）

## 本轮整改映射（F 编号 → 现状，须给代码证据行号）

- **F1（旧 chat 流污染新问题历史）** → `src-tauri/src/orchestrator.rs` search_then_request：检索开始即 `llm.cancel(kind)` + `req_seq.remove(kind)`——旧流 chunk/Finished 在 on_llm_event 因绑定移除被整体丢弃；随后 SearchDone 复查 sgen+epoch 才 bind_request 新请求。同时前端 searching 态增加停止按钮（llm_stop 链入 on_stop：cancel + sgen/req_seq/failed 清）。
- **F2（拒绝后旧流未失效/失败不可见）** → `crates/dongyi-llm/src/lib.rs` `request()` 重构：同一 live 锁临界区内「摘除并取消同 kind 旧任务 + 取消 warm 让位 + 登记新任务」，**拒绝（离线闸门）路径也先取消旧任务**再发 Failed；`bind_request` 拒绝路径额外向前端 emit `llm:reset`（清 activeReq/缓冲），随后 Failed 经未绑定态免检直达。chip 单独切换（on_kind_provider）依旧不取消在途流——这是用户明确语义，不得判缺陷。
- **F3（provider 切换事务）** → `on_kind_provider` 重写为 SharedCfg 锁内单事务：「当前内存快照 → 构建候选 → save_config → 成功才发布 *guard=cand」，失败时内存保持原值并 `config:updated` 回传**真实旧 provider**（""=跟随全局）+ 系统级 failed 提示；不再中途 load_config 覆盖内存。
- **F4（截断展示）** → `src/App.tsx`：LlmMsg finished 类型带 `truncated`，ResultState 增加 `truncated?: boolean` 并在 done 状态区显示「响应可能不完整（流被截断）」+ 重试按钮。
- **F5（保活期间业务在途）** → `crates/dongyi-llm/src/lib.rs` preheat/keepalive：在同一 live 锁内「检查业务 kind 在途 + 登记 warm」原子化；业务在途的保活 tick 直接跳过（让位）；并显式 `is_loopback_base` 校验（仅本机承诺落地）。
- **F6（跨 UTF-8 拆分截图断言）** → mock 测试 payload 以显式字节 `E7 94 B5`(电) 构造，切点取 `windows(3).position(==E7 94 B5)+1`——真正切进「电」的 UTF-8 序列内部；并新增 `mock_离线重定向零跟随`：offline 收到 307 → 断言 Failed(307) 且目标端口**零连接**（nonblocking accept WouldBlock）。
- **F7（同源比较漏 scheme）** → redirect policy 同源判定改为 `scheme() + host_str() + port_or_known_default()` 三元全等（禁 HTTP/HTTPS 互换与默认端口混淆）。
- **F8（Stop 清 failed / mock 证据边界）** → on_stop 增加 `s.failed.remove(kind)`；断连断言 helper `assert_disconnected` 只认可确断连语义（EOF/WSAECONNRESET 10054/WSAECONNABORTED 10053）；全部 mock server 经 `with_mock_server` catch_unwind + `recv_timeout(6s)` 有界等待。
- **本轮实测后新增改动（用户实测两轮）**：
  - 输入翻译提交保留原文（`App.tsx` InputView 提交不再 setDraft("")——Python _submit_input 不清 input_editor 语义；追问仍清）。
  - 置顶跨会话保持（Python open_at 不重置 _pinned）：begin_session 不清 pinned、不在新会话发 popup:pin off；on_pin 同步 `session.pinned`；open_popup 末尾回放 `popup:pin{on}`；前端 popup:open 不再自清 pinned。
  - fire_debounced / open_popup 增加诊断日志。
  - 注意构建事实：`frontendDist` 编译期内嵌，前端改动必须重编 exe。

## 实测确认（需求方 2026-10-13）
- 输入翻译 Enter 后保留原文 ✓
- 置顶跨会话保持（日志 pinned=true 连续回放）✓
- 主流程使用热键路径 ✓
- **浮标在弹窗开着时静默划词常不显示——需求方明确弃审，属 capture 静默路径已知限制（执行文档 §10 已记录），不得判为 P3 缺陷**。

## 复审方法
读代码核对上述每项（证据行号）；跑 `cargo test --workspace --locked`、`npm run build`；静态审查新引入面：request() 单临界区重构、open_kind_provider 单事务、search_then_request 前置取消、redirect policy、mock 测试语义。

## 约束
只读分析 + 无副作用构建/测试；禁止启动/重启 exe（运行中的应用占锁）；产出写唯一文件 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3_FINAL2.md`。

## 产出要求
每项证据行号 + 结论；新发现按 BLOCKER/MAJOR/MINOR 分级（文件:行号/原因/修复建议）；末列 P4 关注点；最终判定 **PASS（P4 可开工）/ FAIL（必修清单）**。
