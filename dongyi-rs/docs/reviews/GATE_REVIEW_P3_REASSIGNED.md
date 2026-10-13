# 懂译 P3 重派 Gate 审查

日期：2026-10-12。**判定：FAIL，P4 不得开工。**

依据：根目录《Rust重构执行文档》§7–8、Python `llm.py`、当前 Rust/React 源码。保留已有 `GATE_REVIEW_P3.md`；本报告为独立复核，不直接继承旧结论。未修改实现，未调用真实云端 API，未操作桌面。用户三轮实测的逐轮操作与结果未在仓库找到，下面区分代码修复和实际验证，不能据注释认定实测通过。

## 阻断项

| 编号／等级 | 位置 | 触发、影响与解除要求 |
|---|---|---|
| R1／高：取消竞态仍在 | `crates/dongyi-llm/src/lib.rs:157,174,243` | 分配 token 后只将 Sender 交给任务，任务开始才 subscribe，没有携带所属 token 或核对当前代次。A 入队→cancel→A 启动时，取消值成为接收器初值，A 仍发 HTTP；同 kind 快速替换同理。原子递增和 send_replace 分离也不能保证并发写入顺序。每请求独立取消状态，在启动及事件投递前核验，覆盖启动前取消和快速替换。 |
| R2／高：流结束与错误误判 | `crates/dongyi-llm/src/lib.rs:328,363,405` | `done:true`／`[DONE]` 仅让 parse_line 返回，读取循环继续等 EOF；保持连接会等到 60s 后报死流。EOF 无条件成功，HTTP 200 的 error 对象被忽略，截断可显示完成；Ollama 最终行含 content 时被丢弃。等待响应头仅有连接超时，没有读等待期限。解析应区分增量、完成、错误，完成立即结束，截断明确报错，并覆盖响应头等待。 |
| R3／高：前端终态被缓冲覆盖 | `src/App.tsx:131,154,186,200` | 确定性顺序：chunk("甲")→finished(full_text="甲")→rAF，得到"甲甲"并退回 pending。failed/stopped/reset/pending 同样未处理旧缓冲；前端类型与处理也不使用 req_id。chat finished 不更新 results.chat 为 done。统一处理缓冲与终态，按请求 ID 隔离，验证上述事件顺序。StrictMode 注销修复不能解决此问题。 |
| R4／高：严格离线存在外发路径 | `crates/dongyi-llm/src/lib.rs:164,194,207,281` | offline 只在 request 检查 provider；远程 Ollama URL 仍获准。预热和保活绕过检查，启动配置 openai+offline 可发云端请求。Python 基线已检查 loopback；当前 reqwest 默认重定向也未约束。所有入口共享目标校验，预热限定本机，并验证禁止路径零请求及重定向。 |
| R5／高：拒绝错误被自身过滤 | `src-tauri/src/orchestrator.rs:372,841` | 离线拒绝时引擎发送 Failed 并返回 false；bind_request 仅在 ok 时绑定 req_id。编排因此丢弃这条失败事件，前端无明确错误；若已有旧请求，拒绝还发生在取消旧槽之前。离线路由应与 Python 强制本地语义一致，准入失败也须可见，旧任务替换语义须明确。 |
| R6／高：关闭／停止／新会话失效不完整 | `src-tauri/src/lib.rs:72,286`；`orchestrator.rs:507,615,659,802` | 新原文会话清 req_seq 已能过滤多数旧事件，但不取消其他 kind 旧流；关闭按钮及托盘隐藏绕过 close_all。close_all/on_stop 不清 req_seq，排队事件仍可通过。输入热键清前端原文与结果，却保留后端旧 source/history/请求绑定，可继续接收旧内容。统一生命周期入口，明确“切输入标签”和“新输入会话”，取消并作废旧请求。 |
| R7／高：检索线程可重新绑定旧请求 | `src-tauri/src/orchestrator.rs:340,372` | 检索完成在线程检查 epoch 后直接 bind_request，与编排的新会话/关闭不是串行事务；检查后切会话仍可将旧原文请求绑定进新会话。停止检索时只取消 LLM 槽，检索完成后还会发起 LLM；同 kind 多次检索也无独立代次。完成结果交回编排线程，按会话与请求代次复查后再发起；停止须作废检索。 |
| R8／中：预热与保活未达到里程碑 | `crates/dongyi-llm/src/lib.rs:194,207,281`；`orchestrator.rs:241` | 请求体无 options.num_predict=1，warm 为普通生成；用户请求不取消 warm，可能占 Ollama 队列。壳仅调用 preheat，未调用 keepalive。silent 失败仍产生 Failed。落实本机单 token、真实请求优先、定时保活和静默事件隔离。 |
| R9／中：P3 单测缺失 | `crates/dongyi-llm/src/lib.rs` | 实际 cargo test 显示 LLM 为 0 tests；4 个测试全部属于 core 配置。至少用本地 mock 覆盖中文跨块、终止/错误/截断、取消与过期事件、离线零请求、预热参数/保活触发；前端验证终态先于 rAF。补三轮实测问题→修复→复测的对应记录。无需真实密钥或大规模测试。 |

另：`orchestrator.rs:810` 输入后端切换先改内存，忽略写盘错误，与注释“双写”及全局配置保存的失败语义不一致；需保持写盘失败时状态可解释并向前端返回错误。

## 已确认的修复与 P2 边界

- AppEvent::Pin 已存在，旧报告的 Pin 编译错误不再成立。
- LLM 回调现经编排过滤 req_id 后转发；新原文清空绑定，修复了直接无条件转发的大部分污染路径，但 R6/R7 尚未闭环。
- React async listen 增加 disposed 与注销逻辑，处理了 StrictMode 双挂载监听泄漏；没有端到端证据证明三轮反馈全部消失。
- 承认需求方此前放行 P3，不追溯否定 P2 授权。但 P2 残留仍可影响本阶段：capture submit 仅 Silent 更新 latest，worker 不感知关闭 epoch，显式 UIA 成功路径不复查目标；防抖和浮标计时线程检查后直接操作存在竞态。消费侧丢弃不能撤销已发送 Ctrl+C。应统一共享有效性，并将防抖/超时事件交回编排处理。

## 实际验证

- `npm run build`：通过 TypeScript 与 Vite 构建。
- `cargo test --workspace --locked`：首次遇到 std/dongyi_capture 元数据错误；模块测试后再运行通过。因此不将首次错误列为源码阻断，也不沿用旧报告编译失败结论。
- `cargo test -p dongyi-llm -p dongyi-core --locked`：通过，core 4 tests，LLM 0 tests。全工作区复核也是仅 core 4 tests。
- 上述竞态与事件反例为源码推演，未声称已经桌面端到端复现；构建通过不证明流式正确。

读取版本 SHA256（非原子快照）：

```text
crates/dongyi-llm/src/lib.rs  4F2F8C6F0944D4338B235786968387A3FE9C0A59FF28E217D042794455D2F997
src-tauri/src/orchestrator.rs 9791234A63A08785747C1C37D3BC3B5AF60B0381BD1DC1158FDFC48EE1DF04F0
src-tauri/src/lib.rs          5F1A8B0F031F3E4EB460C23D5C934A38DEA9E3A53C78C004A92BC104C40A8D84
src/App.tsx                   2314455B111300509667E07889CDE3E86E7FA7E08F9844D06EB3617A8D106E1C
```

解除闸门：修复 R1–R9 及影响 P3 的生命周期残留，补针对性验证和三轮复测记录，以稳定版本重新审查。**本轮不放行 P4。**
