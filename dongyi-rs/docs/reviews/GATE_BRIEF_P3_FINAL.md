# P3 最终复审 Brief（Gate Final Re-review）

你是阶段复审人，复核『懂译』Python→Rust 重构 **P3 阶段**整改。

## 前置报告（必读）
1. `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3.md`（首次 FAIL，B1~B8）
2. `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3_REREVIEW.md`（二次复审 FAIL，RR1~RR7，本轮整改对象）

背景：RR1~RR7 已全部整改完毕，`cargo test -p dongyi-llm` 10 项单测全绿，应用重建并运行中，用户两轮实测通过（最近确认"解释正常有了"）。请逐项核对后判定 **PASS（P4 可开工）/ FAIL**。

## 整改映射（RR 编号 → 现状，须给代码证据行号）

- **RR1（离线重定向仍可外发）** → `crates/dongyi-llm/src/lib.rs` stream_chunks 内 reqwest Client 构建：`redirect` Policy——offline 一律 `Policy::none()`；在线 custom 策略仅允许同源（host+port 不一致即 `error("cross-origin redirect blocked")`），上限 5 跳。
- **RR2（检索复活/污染新会话）** → `src-tauri/src/orchestrator.rs`：search 线程只做抓取并回投 `AppEvent::SearchDone{kind, context, sgen, epoch_at_start}`；LLM 启动唯一入口在编排线程的 `on_search_done`——复查 `req_epoch==epoch_at_start` 且 `search_gen` 匹配才 `bind_request`；`on_stop` 移除该 kind 的 search_gen+req_seq 作废在途检索；检索失败 ctx 为空直接 bind（回退模型自身知识，Python err 分支同款）。chat/explain 消息在 on_search_done 按当时会话全新组装。
- **RR3（离线拒绝事件被丢）** → `bind_request` 对拒绝路径也 `req_seq.insert`（编排单线程通道顺序保证 failed 事件能转发）；前端 `src/App.tsx` failed 处理：`req_id=0` 免检 + activeReq 未绑定（闸门拒绝没有 pending）也放行；仅"绑定中且 req 不匹配"才丢。
- **RR4（生命周期语义未闭合）** → `close_all`/`on_stop`/`begin_session` 清 req_seq/search_gen/failed；输入热键在弹窗已开时改发 `popup:tab` 轻切标签（不再空原文 popup:open 清会话，前端仅 setKind+activate_tab）；`on_tab(explain)` 失败自动重发：清 failed+requested 后走 `dispatch_request`。**注意：绝不能在 on_tab pre-insert requested——dispatch_request 自带去重会吞掉请求，曾致"解释永无输出"回归，本轮已修，请复核该顺序正确性**。
- **RR5（warm）** → 引擎 `request()` 业务请求 `cancel_kind("warm")` 让位；`preheat`/`keepalive` 非 ollama 直接跳过；keepalive interval 首 tick 先消费（首轮真实保活延后 25min）；warm 任务完成后从 live 表摘除 token。**用户语义确认：kind provider chip 切换（on_kind_provider）不得取消在途流——在途本地流继续输出至完成，切换只影响下一次请求。这是预期行为，请勿记为缺陷**。
- **RR6（mock 回归测试）** → `crates/dongyi-llm/src/lib.rs` 测试模块新增 2 个真实 socket mock：`mock_跨块中文_终止行后立即断连`（NDJSON 行拆两次写、断点切入「池」的 UTF-8 字节中间、done 行后服务端保持连接、要求 Finished<2s 且 truncated=false 且客户端断连）；`mock_取消即断连`（收到首个 chunk 后 cancel，服务端须观察到断连；Windows 上客户端 drop 带未读数据时 peer read 收到 10053/10054 RST 均视为断连——属平台语义，代码有注释）。全部测试 10 项通过。
- **RR7（切换写盘失败语义）** → `on_kind_provider`：候选配置先 clone 修改 → `save_config` 成功 → 才替换内存并 emit `config:updated`；写盘失败则内存不动 + 向前端发系统级 failed 提示。保留 key 未配拒绝回滚。
- **附带改动** → `LlmEvent::Finished` 增加 `truncated` 标志（EOF 无终止行仍完成但标注截断），编排层 `llm_event_json` 透传，前端状态区显示截断提示。

## 复审方法
读代码核对上述每项（含证据行号）；跑 `cargo test --workspace --locked` 与 `npm run build`；静态查新缺陷，特别关注本轮新引入路径：SearchDone 重组装、on_tab/dispatch_request 去重顺序、redirect policy 闭包捕获、on_kind_provider 双锁改进。

## 约束
只读分析 + 无副作用构建/测试；禁止启动/重启 exe（运行中的应用占锁、禁动用户桌面）；产出写唯一文件 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3_FINAL.md`。

## 产出要求
- 每整改项证据行号 + 结论
- 新发现按 BLOCKER/MAJOR/MINOR 分级（文件:行号 / 原因 / 修复建议）
- 最终判定 **PASS（P4 可开工）/ FAIL（必修清单）**
- 末尾列 P4 关注点
