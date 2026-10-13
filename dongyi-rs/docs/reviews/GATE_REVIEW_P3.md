# 懂译 P3 Gate 审查（含 P2 遗留回归）

审查日期：2026-10-12。依据：《Rust重构执行文档》§7、§8，前次 Gate 报告，以及 Python llm.py / app.py 基线。审查磁盘源码，不修改实现，不操作用户桌面或真实云端 API。

**判定：FAIL。P4（ArtCraft UI 全量精修、设置页、主题）不得开工。**

本轮发现实现缺陷，不只是验收资料不足。修复后须以稳定版本复审。

## P3 阻断项

| 编号 | 证据位置 | 问题、触发及修复要求 |
|---|---|---|
| B1／高 | crates/dongyi-llm/src/lib.rs:148、225 | request 分配 token 后只传 Sender，异步任务启动时才 subscribe；不携带或核对所属 token。若 request A→cancel 或 request B→A 才开始执行，之前变化已被标记为 seen，A 仍发 HTTP。并发 fetch_add 后 send_replace 也可能乱序写回。要求每请求持独立取消状态/请求 ID，发请求及事件回调前核验；覆盖任务启动前取消和同 kind 快速替换。 |
| B2／高 | src-tauri/src/orchestrator.rs:209、503、544、686；src-tauri/src/lib.rs:71 | 新弹窗只重置 session，不取消其他 kind 的旧流；LLM 事件仅有 kind，没有请求/会话 ID，并直接发前端后才进入编排。原文 A 的 explain/chat 可继续写入原文 B，旧 chat 完成还可能与 B 的 last_question 配对入历史。关闭按钮 hide_popup 和托盘隐藏绕过 close_all，继续生成；输入热键发空原文事件但不清后端旧会话。要求统一关闭/新会话入口、取消所有旧任务，在编排及前端均过滤过期 ID；明确输入视图切换与新会话语义。 |
| B3／高 | src/App.tsx:111、131、154、186、200 | rAF 缓冲未在 finished/failed/stopped/pending/reset 时排空或丢弃。确定性反例：chunk("甲")→finished(full_text="甲")→rAF，结果变为"甲甲"且状态退回 pending；停止/失败也会被迟到 flush 覆盖。同 kind 新请求可混入旧缓冲。要求将终态与缓冲处理统一，并按请求 ID 隔离；覆盖终态先于 rAF 的顺序。chat finished 未将 results.chat 标为 done，完成后仍显示请求中。 |
| B4／高 | crates/dongyi-llm/src/lib.rs:148、179、192、266 | 严格离线仅在 request 检查 provider，不验证 Ollama base_url 为 loopback；offline=true + 远程 Ollama 地址仍外发。preheat/keepalive 直接走 run_stream，完全绕过离线闸门，默认 openai 时启动即可发云端请求。Python 基线有 loopback 检查。要求所有入口共享离线校验，校验实际目标地址及重定向；用本地 mock 证明禁止路径零请求。 |
| B5／高 | crates/dongyi-llm/src/lib.rs:179、192、266；src-tauri/src/orchestrator.rs:230 | 预热/保活注释声称 num_predict=1，但请求体没有 options.num_predict，实际为普通完整生成；warm 独立槽也不会给用户请求让位。keepalive 只有定义，没有壳层调用。warm 失败仍发 Failed(kind=warm)，违反静默约定。要求本机单 token 预热、真实请求优先、启动保活计时，并隔离预热事件；验证请求体和计时触发。 |
| B6／高 | crates/dongyi-llm/src/lib.rs:306、340、380 | HTTP 200 中的 {error:...} 被忽略，EOF 无条件成功；中途截断会显示已完成。[DONE]/done:true 不结束读取，需等连接关闭，服务端保持连接时最终误报 DeadStream。Ollama done:true 行若含 content 也被丢弃。send() 等待响应头只有连接超时，连接成功却不返响应头时未受 60s 超时保护。要求区分内容/完成/错误，明确截断策略，完成标志立即结束，并覆盖首响应等待超时。 |
| B7／高 | src-tauri/src/lib.rs:141；src-tauri/src/orchestrator.rs:36 | 本轮 cargo test --workspace --locked 编译失败：E0599，AppEvent 没有 Pin 变体，但 set_popup_pinned 构造了该变体。须提供稳定、完整、可编译的待审版本。 |
| B8／中 | crates/dongyi-llm/src/lib.rs；现有测试输出 | P3 里程碑明确要求单测，dongyi-llm 当前为 0 tests。至少补充有意义的本地 mock 协议/网络测试：分块中文、终止/错误/截断、取消断连及过期事件、离线零外发、预热参数、保活触发；前端补缓冲终态顺序验证。无需真实云端密钥或大规模测试。 |

取消竞态的判断经 Tokio 官方文档核对：subscribe 前发送的值被新 Receiver 视为已读；仅递增原子计数不能修复本实现。[Tokio Sender::subscribe](https://docs.rs/tokio/latest/tokio/sync/watch/struct.Sender.html#method.subscribe)。协议复核参考 [Ollama streaming](https://docs.ollama.com/api/streaming)、[Ollama chat](https://docs.ollama.com/api/chat)。

## P2 遗留修复复核

| 前次编号 | 本轮结论 |
|---|---|
| B1 配置写旧值 | 原缺陷已修复：新配置写盘成功后才替换内存。core 配置往返及未知字段保留测试通过；未执行壳层写盘失败场景。 |
| B2 屏幕边界 | 已加入 rcWork + outer_size 的物理坐标 clamp，原缺少边界限制的问题有实质修复。尚无四边/混合缩放完整记录；跨屏后 DPI 改变窗口尺寸仍需实测。 |
| B3 超时/防抖 | 已消费 icon_timeout_s/debounce_ms 并增加 epoch。但计时线程“检查 epoch→hide”不是串行事务，检查后新候选显示仍可能被旧计时隐藏；应将超时事件交回编排线程复查并隐藏。 |
| B4 请求有效性 | **未完整修复，继续阻断。** capture worker 不感知关闭 epoch；submit 仍只有 Silent 更新 latest，Explicit 不使旧静默失效。Esc/新热键后旧静默任务仍可能执行剪贴板兜底（即使 UI 消费最终丢弃）。Explicit 仅在兜底前核对目标窗，UIA 成功路径未核对，排队切窗可把新窗口选区交给旧请求。另 fire_debounced 在线程检查 seq 后才分配新 epoch；Esc 可插入两者之间，旧候选反而取得关闭后的新 epoch 并被接受。要求 worker 在 UIA、发键及投递前共享有效性核验；防抖提交也经编排串行处理。证据：crates/dongyi-capture/src/lib.rs:727、761；src-tauri/src/orchestrator.rs:338、357、395。 |
| B5 跨应用证据 | docs/P0-P2验收记录.md 的实际/通过栏仍为空。执行文档记录需求方曾跳过复审放行 P3，此授权予以承认，不追溯否定；但不等于完整回归已通过。需补齐本轮剩余用例，尤其 PDF/终端排除、富格式剪贴板与恢复、关闭迟到结果和混合缩放。 |

inside_own_ui 已包含 settings；React 19/npm 和 COM MTA 偏差已在执行文档登记，当前不作为阻断项。

## 实际验证与版本限制

- npm run build：通过 TypeScript 检查及 Vite 构建。
- cargo test --workspace --locked：失败，B7 所述编译错误。
- cargo test -p dongyi-llm -p dongyi-core -p dongyi-capture -p dongyi-trigger --locked：通过；core 4 个测试，llm/capture/trigger 均为 0 个测试。
- 未执行真实 LLM/跨应用桌面验收；静态反例未声称已做端到端复现。构建成功不能证明流式、取消或剪贴板恢复正确。
- 审查期间 src-tauri/src/lib.rs 有更新：初读尚无 Pin 命令，编译时已出现。B7 是本次实际编译结果，不能代表随后未复核的版本。

本轮结束前记录的 SHA256（用于识别已读取源码，非原子快照）：

```text
src-tauri/src/lib.rs          238FAE009146A8420570677529889D5C4F566D3E950EA7FF407358A401390EB1
src-tauri/src/orchestrator.rs B59C81D711E8CA8FE39D0AA5033F9D957B805C932C49D5D963597800D8A9ED70
src/App.tsx                   571682EEC63C153292E63B0E4389EE9BE84601B3E2A542F66296F0613B49EC3C
crates/dongyi-llm/src/lib.rs  6CA77A2D13E3ACC84428BBFCB51A63D9BD0FCF59921C7923F2580F08C65B57AA
```

放行条件：修复 B1～B8 和 P2 时效性残留，补齐针对性验证与尚未完成的回归记录，再以稳定版本复审。**本报告不放行 P4。**
