# 懂译 P3 整改 Gate 复审

日期：2026-10-13。**判定：FAIL，P4 不得开工。**

依据：`GATE_REVIEW_P3.md`、重派审查报告、根目录《Rust重构执行文档》§7–8、当前磁盘源码和本轮命令执行。承认用户三轮实测及已修复反馈，但不能据此推定未覆盖的并发与离线路径正确。本轮未修改业务实现、未操作桌面、未调用真实云端 API。

## 仍需解除的阻断

| 编号／等级 | 证据 | 触发、影响与整改要求 |
|---|---|---|
| RR1／高：离线重定向仍可外发（原 B4） | `crates/dongyi-llm/src/lib.rs:172–182,399–402` | 初始 Ollama URL 已校验 loopback，但 Client 未配置 redirect policy。本机端点返回 307/308 指向远程，默认策略可继续转发 POST。必须禁用重定向或逐跳校验实际目标，并用本地 mock 验证禁止路径零请求。依赖源码 reqwest 0.12.28 的 `async_impl/client.rs:310` 确认默认使用 `redirect::Policy::default()`，不能仅凭初始 URL 校验宣称闭环。 |
| RR2／高：检索可在停止后复活或污染新会话 | `src-tauri/src/orchestrator.rs:383–409,865–867` | 检索线程检查 epoch 后直接 bind_request：检查→关闭/新会话→绑定旧请求的交错仍存在。Stop 不改变检索代次，停止检索后结果仍会启动 LLM；同 kind 重试也无检索代次。完成消息须交回编排线程，按会话和 kind 代次复查后启动，Stop 作废检索。 |
| RR3／高：离线拒绝错误被丢弃 | `crates/dongyi-llm/src/lib.rs:192–196`；`orchestrator.rs:415–423,934–937` | offline + openai 或远程 Ollama 时发送 Failed 并返回 false；bind_request 只在 true 时登记 ID，失败随后被编排当旧事件丢弃。前端无明确失败，重试 reset 后可一直 pending；拒绝发生在取消旧槽之前，旧流也可继续。准入失败须能正确到达当前请求，替换时须先使旧任务失效。 |
| RR4／高：生命周期语义未闭合（原 B2） | `orchestrator.rs:571–588,719–734,865–867,934–953`；`src/App.tsx:154–162` | close_all/on_stop 不删除 req_seq，已经排队的旧终态仍能通过编排并写 chat_history。弹窗已打开时输入热键仍发送空原文 popup:open；前端清全部结果和 ID，后端却保留旧 source/history/任务。返回解释标签时 requested 已标记，可能不再重发且旧输出被丢弃。区分标签切换与新会话事件；关闭/停止清绑定，新会话统一作废捕获及检索代次。 |
| RR5／中：预热/保活不让位（原 B5） | `crates/dongyi-llm/src/lib.rs:196,222–269`；`orchestrator.rs:267–274` | 用户请求只取消同 kind，从不取消 warm；warm 仍可占 Ollama 串行队列。preheat/keepalive 直接沿用全局 provider，offline=false + openai 会产生云端预热；未落实本机限定。interval 首 tick 立即触发，启动同时发 preheat 和保活；完成的 warm token 不摘除，登记表不断增长。限定本机、业务请求抢占 warm、忙时跳过保活、首轮延后并清登记。Tokio 1.53.2 本地 `time/interval.rs:10,33` 明确首 tick 立即完成。 |
| RR6／中：关键回归测试仍缺（原 B8） | LLM tests 模块；`package.json` | 已有 8 个 LLM + 4 个 core 测试，全绿；并非 12 个 LLM 测试。LLM 主要是行解析和纯函数，预热测试复制构造逻辑，未测试真实发出的 body。缺本地 HTTP mock 的 UTF-8 跨网络块、终止后保持连接、响应头超时、启动前取消/断连、离线重定向零请求、warm 抢占/定时，以及前端 rAF 终态顺序验证。补这些针对性测试即可，无需扩大到真实云端测试。 |
| RR7／中：配置写盘失败语义再次回退 | `orchestrator.rs:899–921` | 输入/追问 provider 切换先修改内存，随后忽略 save_config 错误并向前端宣告成功。磁盘失败时本次运行和下次启动行为不同。按全局 save_config 已采用的顺序，先保存候选配置、成功后替换内存，失败反馈并保留旧状态。 |

这些均为当前源码可推导的路径，未声称桌面端到端复现。RR1–RR5 是实现问题，不能仅靠补验收记录解除。

## 上轮整改对照

| 上轮项 | 本轮结论 |
|---|---|
| B1 取消 | 独立 CancellationToken 修复原 watch subscribe 丢取消值问题。但 request 的取消旧槽与登记新 token 使用分离锁，通用并发 request 可同时存活；select 未在发送前显式检查已取消状态，回调也未复查。壳层通常串行缓解，检索线程直接 request 仍突破该假设，需结合 RR2 和取消 mock 验证。 |
| B2 会话 | 新原文 begin_session 取消全部业务 kind，关闭按钮/托盘进入 Close，确认实质修复；RR2–RR4 残留。 |
| B3 前端缓冲 | finished/failed/stopped 清缓冲，finished 清活跃 ID，chat 标 done，原“甲甲”顺序已实质修复。reset 未清 activeReq，缓冲也未携带 ID，仍须终态/重试/替换顺序回归；不能将静态改善等同自动验证通过。 |
| B4 离线 | request/preheat/keepalive 共用 provider + loopback 闸门已落实；RR1/RR3 未闭合。 |
| B5 warm | num_predict=1、静默事件和保活接线已落实；RR5 残留。 |
| B6 协议 | done/[DONE] 即时结束、最终行 content、200 内 error、响应头 timeout 已修复。EOF 无终止标志仍按成功处理，仅 stderr 告警；这是明确写出的兼容策略，但用户仍无法区分截断。至少增加截断测试并明确用户可见状态。 |
| B7 编译 | Pin 变体已存在，原 E0599 不再作为阻断。实际构建结果见下。 |
| B8 单测 | 从 0 增至 8 个 LLM 测试，RR6 仍未覆盖原要求。 |

## P2 遗留与实测证据

- 防抖和浮标超时已通过 AppEvent 回编排串行处理，原检查后直接 hide/分配 epoch 的竞态已实质修复。
- capture 显式提交淘汰 silent、worker 共用 epoch、UIA 成功路径复查目标、发键前有效性检查均已加入。显式路径仍在校验前调用 UIA，统一 emit 前没有最终复查；消费侧有 epoch 门控。本轮不声称已完成 Windows 捕获端到端回归。
- 根执行文档 §9 只有“三轮实测修复”的汇总，没有逐轮操作→问题→复测结果；`docs/P0-P2验收记录.md` 跨应用矩阵实际/通过栏仍为空。承认此前需求方放行 P3，不追溯否定授权；PDF/终端排除、富格式剪贴板恢复、混合缩放等剩余证据仍需补记。

## 本轮验证

- `npm run build`：通过 TypeScript 与 Vite 构建。
- `cargo test -p dongyi-llm -p dongyi-core --locked`：通过，LLM 8 + core 4。
- 首次 `cargo test --workspace --locked`：失败，std/serde_json/futures_util/windows_interface 等缓存元数据异常；不能据此认定源码编译缺陷。模块测试通过后再次运行全工作区通过：capture 1 + core 4 + LLM 8，共 13 项，壳层/trigger 无测试。原 B7 解除。
- 未做真实 LLM、桌面捕获或真实 25 分钟保活测试。

读取源码 SHA256（非原子快照）：

```text
crates/dongyi-llm/src/lib.rs  1B8B1C451D444545D68E0DBE5800E784944D69327DCD9683BC7E4809C5ADE4CE
src-tauri/src/orchestrator.rs F12ED939812DE6F67119ECDC7E0194B70CBEE7DD5CB0D167A6B553F0D2EDC820
src-tauri/src/lib.rs          12A460B1969A1BF39CDD0A47B65E842352B3FB5D99FC799B2092AB7F7C427877
src/App.tsx                   570D3855629E1B885257B4B611DAAFC03EC3BC0377E73F12C25BAE3314C035FD
crates/dongyi-capture/src/lib.rs 4CB99940BE7610519BFEFB0C59459883252FF1F3915EF95527CB2AFD22F935D5
```

放行条件：解除 RR1–RR7，完成针对性回归并补齐剩余实测记录，再审稳定版本。**本次不放行 P4。**
