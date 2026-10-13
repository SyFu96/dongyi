# 懂译 P3 最终复审 B（F1–F8）

日期：2026-10-13。**判定：FAIL（P4 暂不得开工）。**

F1、F2、F4–F7 的主要实现缺陷已解除；F3 后端事务正确，但前端“跟随全局”回滚仍错误，须修复。F8 有一处 MINOR 测试结果被忽略。构建与现有测试通过不覆盖该配置回滚反例。

## 1. 范围、方法与实际验证

完整读取 `GATE_BRIEF_P3_FINAL2.md`、`GATE_BRIEF_P3_FINAL.md`、`GATE_REVIEW_P3_FINAL.md`，并补读首次及二次复审报告以核对 RR1–RR7 的历史约束。核对当前磁盘源码中的请求替换、检索回投、配置事务、重定向、前端事件及 socket mock；行号对应本次读取版本。

只读分析及构建/测试；未修改业务源码、真实用户配置，未调用真实云端模型，未启动或重启产品应用 exe，未操作用户桌面。Cargo 执行的是指定测试程序。唯一审查文档产出为本文件，dist/target 为正常构建产物。

| 验证 | 实际结果 |
|---|---|
| 首次 `cargo test --workspace --locked` | 失败：rustc 明确报内存不足、LLVM allocation failed；不据此认定源码编译缺陷。 |
| 首次 `npm run build` | 退出码 1，输出停在 transforming，无具体诊断；不能直接归因为代码错误或确定为内存不足。 |
| 串行 `npm run build` | 通过，退出码 0；TypeScript + Vite 8.3.4，19 modules，Vite 构建 17.06s。 |
| 串行 `cargo test --workspace --locked -j 1` | 通过，退出码 0；构建 50.37s，capture 1 + core 4 + LLM 11，共 16 项；壳层、trigger、doc-tests 无测试。 |
| 缓存完成后再次执行原命令 `cargo test --workspace --locked` | 通过，退出码 0；构建检查 0.51s，LLM 11 项耗时 0.09s。 |
| 前端配置回滚定点检查 | 从实际 App.tsx 提取 `config:updated` 注册代码，经项目 TypeScript 转译，在 Node 内注入事件与 setter；旧 override=""、全局 openai、监听器捕获初始 provider="…" 时，期望 openai，实际 ollama。未写额外测试文件。 |

接受 brief 中需求方两轮实测确认：Enter 后保留输入原文、置顶跨会话保持、主流程使用热键。静默划词浮标限制已明确弃审，**不列为 P3 缺陷**。provider chip 单独切换不取消在途流是明确语义，**不列为缺陷**。没有做桌面端到端、真实模型或真实 25 分钟保活实验。

## 2. F 编号整改映射

以下 `LLM` 指 `crates/dongyi-llm/src/lib.rs`，`编排` 指 `src-tauri/src/orchestrator.rs`；前端为 `src/App.tsx`。

| 项目 | 代码证据与复核 | 结论 |
|---|---|---|
| F1：旧 chat 流污染新问题历史 | 编排:397–408 检索开始取消同 kind 并移除 req_seq；:435–449 复查 epoch+sgen；:462–498 从当前会话组装消息后绑定；:1071–1087 先检查绑定才写历史。编排串行消费事件，on_chat_ask 更新问题至 search_then_request 撤销绑定之间没有另一个 LLM 事件处理插入。前端:529–540 searching 提供 Stop；壳层 lib.rs:117–120 转发 Stop；编排:985–993 清检索、绑定、失败标记。 | **主要缺陷已修复。** A 的迟到 chunk/Finished 在 B 检索期不再通过编排，不写 `(B, answer_A)`。未声称有 A→B→A Finished 自动回归。 |
| F2：拒绝替换旧任务及失败可见 | LLM:198–213 同一 live 锁摘除旧 kind/warm 并登记新 token；:214–223 取消旧 token 后才判断离线拒绝、摘除占位并发 Failed。编排:502–512 即使拒绝也登记新 ID，随后 emit llm:reset；引擎事件回到同一编排通道，Failed 在 bind_request 返回后处理。前端:258–262 清旧 activeReq/缓冲，:233–244 未绑定拒绝可见。 | **主要缺陷已修复。** 注意实际 token.cancel 在锁外:214–215，brief 所称“取消也在锁内”并非字面事实；槽位替换原子化、取消先于拒绝发送，当前串行编排下未发现由此重现 F2/F5 的反例。 |
| F3：provider 切换事务及失败回滚 | 编排:1012–1042 单 SharedCfg 锁内读取内存、构建 cand、保存成功才发布；:1028–1036 拒绝/保存失败不写 guard；:1051–1056 回传真实旧 override（含空串）及系统 failed。壳层 lib.rs:37–42 配置 IPC 同锁保存再发布。前端:281–293 用一次挂载捕获的 provider 解读空串。 | **后端事务通过；端到端回滚未闭合。** 见 N1（MAJOR），仍阻断放行。不再中途 load_config 覆盖内存，也无原双锁保存交错。 |
| F4：截断展示 | LLM:550–560 EOF 无终止行返回 true，:381–386 Finished 携带标志；编排:354–355 透传；前端:29、38 定义字段，:229–231 写状态，:553–569 显示“响应可能不完整（流被截断）”和重试。 | **修复通过静态复核。** 截断提示区别于原文长度截断；没有新增 EOF→UI 自动测试，现有正常终止 mock 只断言 truncated=false。 |
| F5：业务优先及本机 warm | LLM:251–254、297–299 显式 loopback；:261–272、307–320 同一 live 锁检查业务 token 并登记 warm，忙则跳过；:198–213 业务登记同时摘 warm，随后取消；:288–290 消费首 tick；:275–277、323–324、339–341 按 token 身份清理。 | **主要缺陷已修复。** warm 检查/登记与业务槽位登记共用同锁，无原“检查闲→业务登记→warm 登记”空隙。非本机/非 Ollama 跳过。未动态验证保活时钟及抢占。 |
| F6：真实 UTF-8 内部切点及离线零跟随 | LLM:884–895 payload 显式 E7 94 B5，windows(3) 找“电”并 +1，在首字节后切片；:929–939 断言全文、非截断、Finished<2s及服务端结果；:1003–1055 offline 307→Failed(307)，目标 listener 非阻塞 accept 必须 WouldBlock。本轮两项 mock 均通过。 | **原字符边界误断言已修复；离线重定向零跟随已动态覆盖。** 两次 TCP 写及 80ms 间隔不保证客户端每次必收为独立块，不能宣称确定性 bytes_stream 分块测试。 |
| F7：同源 scheme | LLM:460–482 offline Policy::none；在线比较 scheme、host_str、port_or_known_default，超限拒绝，无法解析初始 URL 时拒绝 follow。 | **修复通过静态复核。** 原默认端口 None 与 scheme 漏比问题解除；未把离线 307 mock 当作在线降级测试。 |
| F8：Stop failed 与 mock 边界 | 编排:989–991 删除 search_gen/req_seq/failed；LLM:837–854 catch_unwind 回传线程结果，:859–866 仅认可 EOF/10053/10054；:936–940、993–997 检查 recv_timeout(6s) 结果。:1057 重定向 mock 却忽略结果。 | **Stop 与两项流式 mock 修复通过；测试收口部分通过。** 所有 mock 等待均有界，但重定向 mock 可吞掉服务端 panic/超时，见 N2（MINOR）。 |

## 3. 新增实测改动与 RR 约束复核

| 改动/约束 | 证据 | 结论 |
|---|---|---|
| 输入翻译提交保留原文；追问仍清 | 前端:743–750 Enter 仅 onSubmit(draft)，不 setDraft("")；:304–308 追问清 chatDraft。 | 与本轮需求确认一致，通过静态复核。输入视图卸载重建时 draft 的生命周期不属于“提交后保留”的这项结论。 |
| 置顶跨会话保持 | 编排:520–533 begin_session 不清 pinned；:648–652 同步 atomic/session 并回传；:823–827 open_popup 回放真值。前端:155–165 popup:open 不清 pinned，:272–274 接收回放。 | 通过静态复核，接受需求方实测确认。源码:88及文件头:8–9 仍有旧“重置/未固定”注释，不作为功能阻断。 |
| 诊断日志 | 编排:570–584 防抖跳过/拒绝日志，:827 弹窗 kind/pinned/text_len。 | 已落实；不以日志替代 UI 或请求身份核验。 |
| frontendDist 内嵌边界 | src-tauri/tauri.conf.json:8 为 ../dist，壳层 lib.rs:237 使用 generate_context。 | npm 构建只验证前端产物；本轮未构建/替换运行中发布 exe，也不声称当前运行实例包含本轮源码。前端整改交付仍需重新构建产品 exe。 |
| RR2/RR4 迟到与解释惰性 | 编排:435–449 双门；:520–533 新会话清绑定/检索/失败；:672–686 close 推进 epoch、取消、清绑定；:875–890 先移除失败/requested，再调用自行去重的 dispatch_request:365–383；前端:265–269 popup:tab 轻切。 | 原停止检索复活、关闭旧终态写历史、解释 pre-insert 吞请求未重新引入。 |
| RR5 chip 用户语义 | 编排 on_kind_provider:1000–1060 未调用 llm.cancel。 | 保持在途流，下一请求使用新配置，符合用户明确要求。 |

## 4. 新发现与修复建议

### N1／MAJOR：F3 前端失败回滚误解“跟随全局”，实际模型与 chip 不一致

**证据：** `src/App.tsx:77,102–116,123,281–293`；`src-tauri/src/orchestrator.rs:1015,1033–1036,1051–1056`。

provider 初值是“…”；注册事件的 useEffect 依赖为 []，监听器持续捕获首次渲染的值。异步 get_config 的 setProvider 不更新已注册闭包。因此 `followOpenai = provider === "openai"` 实际一直为 false。

**具体反例：** 当前全局 provider=openai，input/chat 没有 override（旧值空串），初始 chip 正确显示联网；用户切本地，保存失败。后端保留全局云端并 emit config:updated(provider="")，前端却显示本地。后续提交仍使用云端，用户看到的模型选择与实际目标不一致。系统 failed 提示不能恢复正确 chip。即使初次保存未失败，成功切回空串也同样错误。

定点执行实际注册代码、注入首次渲染捕获值“…”与空串回滚事件，输出为 expected=openai、actual=ollama、matches=false。该检查验证处理函数，未触碰真实配置，也不宣称做了写盘失败桌面复现。

**修复建议：** 使用更新到当前配置的 ref，或后端回传实际 effective_provider；明确区分空串跟随全局、显式 ollama、显式 openai。当前 `isCloud ? "openai" : followOpenai ? "openai" : "ollama"` 也没有限定只有空串才跟随，简单增加 effect 的 provider 依赖仍会使全局云端下的显式 ollama 被错误显示为云端。只需定点验证全局云端+空串回滚、全局云端+显式本地两个映射，再复审，不要求重跑桌面矩阵。

### N2／MINOR：重定向 mock 忽略服务端结果，panic/超时仍可能测试通过

**证据：** `crates/dongyi-llm/src/lib.rs:1017,1057`，对照 `:936–940,993–997`。

服务端 assert_disconnected 的失败经 catch_unwind 变为 Err，但最终 `let _ = server_rx.recv_timeout(6s)` 把 Err、通道断开及 Timeout 全部吞掉。目标零连接与 Failed(307) 仍有有效主线程断言，因此不撤销 F6 的核心零跟随证据；服务端断连与完成证据不能视为强制通过。

**建议：** 使用与另两项 mock 相同的 match，对 Ok(Err)、Timeout、Disconnected 明确失败。超时后 worker 线程可仍阻塞，但主测试不会无限 join；不要宣称 helper 保证服务端线程自身终止。

未发现新的 BLOCKER。F2 的取消实际位于锁外、TCP 写不保证读分块等边界已在映射表明确记录，不将注释或测试名称当作额外证明。

## 5. 判定与必修清单

**FAIL。P4 暂不得开工。** 必修 N1：F3 的后端事务已正确，前端真实 provider 回滚仍未闭合，且会造成实际云端与“本地”显示不一致。修复上述映射并提供定点证据后可复审；无需重做已确认的 Enter/置顶实测，也不得改掉 chip 不取消在途流的语义。N2 应一并修正，属于测试收口缺陷，不单独作为本轮功能放行阻断。

本轮读取后记录 SHA256（非原子快照，不代表运行中 exe）：

```text
src/App.tsx                   4231037A6E9CFA80C98950AC0C24E663126C6033E3F9DB836A0D48AD588494AA
src-tauri/src/orchestrator.rs 5257BBBCAE8C6B4CD7F28A638011755930200A69224BCBFFF52E25D67B7B3853
src-tauri/src/lib.rs          12A460B1969A1BF39CDD0A47B65E842352B3FB5D99FC799B2092AB7F7C427877
crates/dongyi-llm/src/lib.rs  5D1B95C99879BD1BC9BEB9C0E7137FC77B2BCC395A779A0A1A66E3C9F5146F14
```

## 6. P4 关注点

- 设置页、provider chip 共用正确的实际配置映射与保存事务，展示跟随全局、显式本地/云端及失败回滚。
- 保持请求身份、检索代次、终态清缓冲和解释惰性派发顺序；UI 精修不要重新引入 pre-insert 去重回归。
- 后续只补有价值的确定性用例：EOF 截断提示、旧 chat 终态隔离、拒绝替换及可控时钟的 warm 让位；不把现有 11 项 LLM 测试描述为这些路径均已覆盖。
- 保留 Enter 原文、跨会话置顶、不抢焦点及交互标签激活；交付前端改动须重建产品 exe。本轮不动运行实例。
- 继续补 P2 混合 DPI、PDF/终端、富格式剪贴板恢复等既有证据；承认此前授权，不追溯否定。静默划词限制按需求方弃审边界记录，不重新作为 P3 缺陷。
