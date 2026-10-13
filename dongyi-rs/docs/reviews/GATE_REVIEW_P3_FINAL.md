# 懂译 P3 最终复审

日期：2026-10-13。**判定：FAIL（P4 不得开工）。**

已完整读取 `GATE_BRIEF_P3_FINAL.md`、首次报告 `GATE_REVIEW_P3.md`、二次报告 `GATE_REVIEW_P3_REREVIEW.md`，随后核对当前磁盘源码；另查阅根目录《Rust重构执行文档》及 `docs/P0-P2验收记录.md`。本报告以源码与实际测试为依据，不将 brief 中的“已整改”陈述直接当作结论。

只进行只读分析及指定构建/测试；未启动、重启产品应用，未操作用户桌面，未调用真实云端 API，未改业务源码。唯一新增报告文件为本文件；构建/测试生成正常的 dist/target 产物及临时测试文件。接受 brief 提供的两轮实测通过及“解释正常有了”反馈，但这些反馈不覆盖下述交错、写盘失败和截断路径。

## 1. 实际验证

| 命令 | 结果 |
|---|---|
| `cargo test --workspace --locked` | 通过，退出码 0；capture 1、core 4、LLM 10，共 15 项；壳层/trigger/doc-tests 无测试。构建 35.60s，LLM 测试 0.09s。 |
| `npm run build` | 通过，退出码 0；TypeScript 检查及 Vite 8.3.4 构建成功，19 个模块，构建 19.06s。 |

没有扩大运行其他测试，也没有做桌面端到端、真实模型或 25 分钟保活实测。测试全绿证明现有断言通过，不证明所有整改要求已闭合。

## 2. 整改映射及结论

下表行号均对应本轮读取的源码，范围用于说明完整路径。

| 项目 | 代码证据 | 结论 |
|---|---|---|
| RR1：离线重定向 | `crates/dongyi-llm/src/lib.rs:173–183` 初始离线闸门；`:424–449` offline 使用 `Policy::none()`，在线闭包 `move` 捕获独立解析出的 URL，仅 host/显式 port 相等才 follow，超过 5 跳拒绝。 | **原离线重定向实现缺陷已解除。** 捕获对象无借用生命周期问题。在线“同源”判定尚不完整，见 F7；未有重定向零请求 mock，不能声称已动态验证。 |
| RR2：检索回投及重组装 | `src-tauri/src/orchestrator.rs:397–426` 工作者只抓取并回投 SearchDone；`:302–304` 主编排消费；`:431–445` epoch+sgen 双门；`:460–494` 从当前会话重组 chat/explain，空 context 也 bind；`:969–970` Stop 作废检索和绑定。 | **原检查→跨线程 bind 竞态及 Stop 后检索复活已修复；整体未闭合。** 新检索未撤销旧 LLM 绑定，可污染新问题及历史，见 F1。 |
| RR3：拒绝事件 | `orchestrator.rs:498–508` 无论入队成功与否均登记 req_id；`:1045–1049` 后端按该 ID 过滤；`src/App.tsx:231–242` 系统 req_id=0 和未绑定态放行。 | **无活跃请求时拒绝可以直达，部分修复。** 替换活跃请求的拒绝仍被前端丢弃；引擎拒绝仍先于取消旧槽，见 F2。 |
| RR4：生命周期及解释去重 | `orchestrator.rs:513–527` begin_session 清绑定、检索、失败、历史；`:658–683` close 清绑定/检索/失败并推进 epoch；`:965–973` Stop 清绑定/检索；`:815–835` 已开弹窗发 popup:tab；`App.tsx:263–268` 仅切标签/activate_tab；`orchestrator.rs:855–870` 失败先移除 failed/requested，再 dispatch，`:365–383` dispatch 独自 insert 去重。 | **关闭旧终态过滤、输入热键轻切、解释请求顺序通过静态复核。** 没有 pre-insert 吞请求回归。Stop 未清 failed，且 searching UI 不提供 Stop，见 F8/F1。begin_session 本身不推进 req_epoch，但清 search_gen 已足以淘汰旧 SearchDone；不据此误报旧检索跨会话复活。 |
| RR5：warm | `LLM lib.rs:198–210` 已准入业务请求取消 warm；`:228–255` preheat 非 ollama 跳过并完成摘 token；`:264–290` 消费首 tick、25min 后执行并摘 token；`:395–397` 实际 body 注入 num_predict=1；`orchestrator.rs:276–283` 启动接线。 | **抢占现有 warm、禁云端 warm、延后首轮保活及 token 清理已落实；优先级未闭合。** 业务在途时保活仍可新启动，见 F5。仅检查 provider，offline=false 的远程 Ollama 仍可预热，故不能描述成“仅本机”。provider chip 切换不取消在途流是用户明确语义，本报告不将它判为缺陷。 |
| RR6：socket mock | `LLM lib.rs:769–853` 实际 socket、拆行、done 后保持连接、Finished<2s、truncated=false、检查客户端断连；`:858–932` 首 chunk 后取消并检查断连；本轮 10 项 LLM 测试通过。 | **有实质网络测试，但不完全满足 brief。** `:801–806` 拆分点在完整“池”之后，并未切进 UTF-8 字节；取消断连断言过宽且无有界等待，见 F6/F8。其余原报告缺失用例仍不能声称被这两项覆盖。 |
| RR7：配置保存 | `orchestrator.rs:983–984` 先加载磁盘并覆盖共享内存；`:1005–1029` 候选修改→保存→第二次内存替换；`:1019–1026` 保存失败返回 failed；`:991–1001` 未配 key 返回回滚及系统 failed。 | **候选 provider 的写盘顺序改善，但整体未修复。** 保存前已有内存写入，双锁之间可与 save_config IPC 交错；失败提示也没有回传当前 provider，见 F3。 |
| 附带：截断提示 | `LLM lib.rs:63,347–352,505–521` 正常终止 false、无终止 EOF true，Finished 带标志；`orchestrator.rs:354–355` 透传。 | **后端通过，前端未实现。** `App.tsx:29,33–38,227–229,540–542` 不接收、不保存、不显示该标志；`:157,462` 现有 truncated 仅用于原文长度，见 F4。 |

## 3. 必修发现（MAJOR）

没有发现需单列为 BLOCKER 的编译失败或本轮离线重定向直接外发路径；以下 MAJOR 仍阻止 P3 放行。均为源码可推导反例，未声称已做桌面复现。

### F1：新检索期间旧 chat 流仍有效，可把旧回答记在新问题下（RR2 残留）

**证据：** `orchestrator.rs:885–887,909–911,397–404,1045–1056`；`App.tsx:302–311,274–276,193–205`。

**路径：** chat A 已绑定并生成；用户提交 B，后端立即把 last_question 改成 B，再开始 B 的检索。search_then_request 只更新 search_gen，没有取消 A 或移除 A 的 req_seq。B 检索未完时，A 的 chunk/Finished 仍通过过滤；Finished 使用当前 last_question=B 写入 `(B, answer_A)`。之后 B 的 SearchDone 又将这份错误历史装入新请求。前端提交 B 重置 chatStreaming，A 的 chunk 还可能被当作 B 的 assistant 气泡。此反例不依赖线程检查竞态，即便编排完全串行也成立。

**修复：** 接受新 chat 问题时立即取消旧 chat、撤销旧绑定，再登记检索代次；历史用请求绑定的问题快照配对，不读取可被后续提交覆盖的 last_question。检索开始同时清前端 activeReq/旧缓冲。补一项有界顺序回归：A 在途→B 检索→A Finished，要求不转发、不入历史。`App.tsx:525–537` searching 仅显示文本而无停止按钮，应让检索也能发 Stop。

### F2：活跃请求被离线拒绝替换时，失败提示仍丢失，旧流也未取消（RR3 残留）

**证据：** `LLM lib.rs:194–201`；`orchestrator.rs:498–504`；`App.tsx:187–190,234–237`。

**路径：** offline=true 的本地 input A 正在运行；用户配置了 cloud key，切 input provider=openai（按用户语义 A 继续）；随后提交 B。引擎发 Failed(B)，没有 Pending(B)，且在 cancel_kind 之前返回。后端绑定 B 后转发 Failed(B)，但前端仍绑定 A，于 `bound != B` 丢掉失败。A 的后续事件则被后端按 B 的绑定丢弃，UI 可一直显示请求中，A 仍占生成资源。

**修复：** 新业务提交先取消同 kind 旧任务再做离线拒绝；让前端收到新请求的权威绑定/准入事件，或在提交时同步撤销旧绑定，避免用宽泛“未绑定就放行”代替完整身份协议。验证 A 在途→B 拒绝，必须可见失败且旧任务失效。chip 单独切换仍保持不取消，只有新提交替换才取消。

### F3：provider 切换仍提前修改内存，且配置事务未串行（RR7 残留）

**证据：** `orchestrator.rs:983–984,1005–1029`；`src-tauri/src/lib.rs:40–46`；`App.tsx:279–285`；`dongyi-core/src/lib.rs:125–149`。

**路径：** 读取配置遇权限/读取错误时 load_config 可返回默认值，`:984` 在候选保存前已经覆盖运行中配置；随后保存失败返回，内存并非进入函数时的旧值。即使保存成功，配置读取→第一次锁→无锁保存→第二次锁并非事务：IPC save_config 可以插入两者之间，导致较新的设置被旧快照覆盖，或磁盘和内存落在不同版本。brief 所称“双锁改进”没有保证事务一致性。当前保存失败只发 failed，没有 config:updated 恢复 provider；若磁盘重载改变了覆盖项，chip 也可能显示旧值。

**修复：** 磁盘刷新不得提前提交；全部配置写入口采用同一互斥事务/串行入口，保留原内存快照，候选保存成功才发布。读错误明确区分默认初始化与运行期刷新失败，失败保留旧配置，并反馈真实旧 provider。用临时路径/注入失败覆盖保存失败及两个写入口交错，不改真实用户配置。

### F4：LLM 截断仍被展示为“已完成”（附带整改未闭合，原 B6 残留）

**证据：** `LLM lib.rs:519–521`；`orchestrator.rs:354–355`；`App.tsx:29,33–38,227–229,540–542`。

**原因：** 后端发送 truncated=true，前端事件类型及结果状态均无此字段，finished 无条件置 done，状态区无条件显示“已完成”。原文截断提示不是回答截断提示。

**修复：** finished 类型及每 kind 的 ResultState 接收并保存标志；状态区明确提示“响应可能截断”，保留已有内容与重试入口。补 EOF 无终止行的针对性用例，并验证前端状态映射。

### F5：保活仍可在业务生成期间新建 warm（RR5 残留）

**证据：** `LLM lib.rs:200–201,268–288`。

**原因：** 业务请求只能取消当时存在的 warm；之后 interval 到点，保活不检查 translate/explain/chat/input 是否仍有活跃 token，直接登记并发送 warm，重新占用 Ollama 资源/队列。不能用“业务入口 cancel warm”推定整个时间区间内 warm 都让位。

**修复：** 在 live 的同一把锁内检查业务忙状态并决定 warm 登记，忙时跳过；业务取消 warm 与登记新业务也应纳入同一调度临界区，避免检查→登记间隙。若承诺“仅本机”，显式检查 loopback。用可控计时验证业务在途时 tick 不发送 warm，无需真等 25 分钟。

### F6：跨 UTF-8 字节回归并未执行（RR6 未完全满足）

**证据：** `LLM lib.rs:800–806`。

**原因：** a 是完整 Rust 字符串 `…电池` 的 as_bytes()，b 从“包”开始，切点在字符边界。注释声称切进“池”的 UTF-8 字节，实际测试只能覆盖一条 NDJSON 行跨两次写。测试通过不能证明声明的 UTF-8 跨块要求。

**修复：** 对完整帧字节数组在“池”的第 1 或第 2 个字节之后切片分写，保留完成耗时/全文/断连断言；必要时通过可控分块流保证客户端确实消费两个块，因为 TCP 两次写不保证两次读取。另补离线重定向目标零连接断言，覆盖 RR1 的既定验证要求。只需这些针对性回归。

## 4. 其他发现（MINOR）

### F7：在线重定向的“同源”比较漏 scheme

**证据：** `LLM lib.rs:435–438`。

比较 host_str+port() 会把默认端口的 `https://host` 与 `http://host` 都视为 `(host,None)`，允许改变 scheme 及实际默认端口；也可能误拒 `http://host`→`http://host:80`。因此它实现了 brief 描述的字面比较，但不是真正同源。这是在线策略收紧不足，offline 的 none 策略不受影响；本报告不声称已验证敏感头转发。

**建议：** 比较 `scheme()+host_str()+port_or_known_default()` 或 URL origin，明确禁 HTTPS 降级，加入轻量策略测试。

### F8：停止清理和取消 mock 的证据边界

**证据：** `orchestrator.rs:965–971` 未删除 failed，与 brief 所述 Stop 清 failed 不符；`LLM lib.rs:898–900` 接受任何 read 错误，不只断连错误；`:863–884,898,932` accept/read/join 均无测试侧有界超时。

**影响：** failed 标记可能遗留；取消测试可能把其他 I/O 错误当成功，网络异常或断连回归可挂住测试。该测试没有断言取消到断连耗时，不能以名称“取消即断连”推定时限已测。

**建议：** Stop 清 failed；仅认可 EOF、ConnectionReset/ConnectionAborted 等明确断连语义并记录错误；为服务端读和完成同步设置短期限。测试应失败退出而非无限等待。

## 5. 判定及必修清单

**FAIL。** RR1 的原离线重定向漏洞、RR4 的解释去重顺序等确有修复，构建和现有测试也全部通过；但 RR2/RR3/RR5/RR7 仍有实现残留，RR6 证据与声明不符，回答截断提示未落地。不能放行 P4。

放行前必修 F1–F6，并提供上述针对性验证；无需重做所有测试或调用真实云端。F7/F8 应随整改处理。不得将“provider chip 不取消在途流”的用户确认行为改成取消。

读取后记录的 SHA256（非原子快照，不代表运行中 exe 与源码一致）：

```text
crates/dongyi-llm/src/lib.rs  527A400CDF4F466AEF5B039F72227630204A8AC0F42E6A5DDCEE3AF7147C89E7
src-tauri/src/orchestrator.rs C2B1268531FE68E9CAD7C24AC6477923E9154E580B8C07586B18AAD2E1BD54DF
src-tauri/src/lib.rs          12A460B1969A1BF39CDD0A47B65E842352B3FB5D99FC799B2092AB7F7C427877
src/App.tsx                   EFAF2D20EE010297B3ACC219D5228FAE3908C2149DEFBDF71D13EEA3EA4682B6
```

## 6. P4 关注点

- 保持检索/生成/停止/失败/截断状态完整，按请求身份隔离缓冲与 chat 气泡。
- provider chip 仅影响下一请求；切换保存失败要显示错误并恢复准确配置，设置页与其他配置写入口共用事务。
- UI 精修期间保留解释惰性派发及去重顺序，避免重新引入“解释永无输出”。
- 保留不抢焦点、输入交互激活、置顶、关闭取消及 mixed-DPI 约束，尤其新会话统一复位。
- P2 跨应用矩阵仍有空栏；承认此前用户授权放行 P3，不追溯否定，但 PDF/终端、富格式剪贴板恢复、混合缩放及稳定性仍应补齐记录，不因两轮 LLM 实测推定通过。
