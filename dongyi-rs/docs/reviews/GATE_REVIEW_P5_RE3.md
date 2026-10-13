# 懂译 P5 定点复审 D

日期：2026-10-13。**判定：PASS；上轮唯二必修 C-M1/C-M2 闭合，可进入 P6。**

本结论仅针对 `GATE_REVIEW_P5_RE2.md` 中 RE-M1 恢复链的两个指定交错。RE-M2/RE-M3/m2/RE-m1/RE-m2 沿用已闭合结论；不代表 P6 验收已经完成。

## 范围与验证边界

K 指 `crates/dongyi-knowledge/src/knowledge.rs`，O 指 `src-tauri/src/orchestrator.rs`，行号以本轮磁盘源码为准。使用 env-list 技能核对环境；未改业务源码、真实配置、TM 或 KB，未启动产品 exe、调用桌面 IPC 或真实模型，未操作运行 exe PID 17624。新增文件仅本报告；Cargo 命令更新正常 target 产物。

| 验证 | 结果 |
|---|---|
| `cargo test -p dongyi-knowledge --locked` | 退出码 0，15 项通过；doc-tests 0 项。 |
| `cargo check --workspace --locked` | 退出码 0，包含 orchestrator 所在壳层的编译检查通过。 |
| 两个指定交错及重试边界 | 下述源码状态机推演；未进行线程屏障、超时或 spawn 故障注入。既有测试通过不作为竞态消除的证明。 |

## C-M1：闭合

证据：K:180–195（入口检查、CAS、成功后复查），K:199–213（读盘、发布守卫、发布顺序），K:275–301（refresh 就绪门）。

按上轮指定交错逐点核验：

1. 第一次 init 在途；另一个 start_init 在 K:181 读到 `init_done=false` 后暂停。
2. 第一次 init 写入索引，再在 K:212 写 `init_done=true`，随后 K:213 写 `init_running=false`。
3. 暂停调用恢复，在 K:186 CAS 成功；K:191 再读取 `init_done`，此时为 true，K:193 复位运行标志并返回。
4. 返回发生在 Arc 克隆和 spawn 之前：没有第二次 init 线程，没有第二次读盘，也没有旧快照再次发布。refresh 随后观察到 done，可继续刷新。

补充挑战：若 CAS 发生在第一次 init 清 running 之前，CAS 失败直接返回；若 CAS 成功且复查仍为 false，则前一初始化尚未完成并释放运行标志的路径不成立。当前代码中 done 只由初始化从 false 写成 true，未发现重置为 false 或其他写入者；运行标志使初始化发布者唯一，refresh 必须先观察到 done 才能发布。因此 K:201 的发布守卫虽位于 state 写锁之外，当前闭合依据仍是 CAS 后复查、唯一初始化者和 refresh 就绪门共同形成的不变量，而非把单独的“检查后写入”当成原子事务。以后增加 done 重置或其他发布入口时需重新审查。

**结论：指定的 start_init 检查/CAS 间隙二次初始化覆盖反例不再成立。**

## C-M2：闭合

证据：O:1220–1239（同锁更新最新 pending、单 worker 门），O:1262–1277（消费目标），O:1278–1294（not_ready 回填和有限重试），O:1296–1306（成功后登记 done、发事件）。

按上轮指定交错逐点核验：

1. worker 取 A：`pending=None, inflight=A, running=true`。
2. 新配置 B 触发 maybe_refresh_kb，在同一 kb_sched 锁内写 `pending=B`；因 running=true 不创建第二个 worker。
3. A 返回 not_ready：worker 持同一锁清 inflight，O:1284 看到 pending 非空，跳过 A 的回填。锁释放时为 `pending=B, inflight=None, running=true`（未到耗尽边界）。
4. worker 解锁后睡眠 200ms，再循环取 B；无需额外 KbCheck/领域触发。若期间来了 C，则同锁把 pending 换成 C，下一轮消费 C，A 不会覆盖它。

无新目标时，pending 为空才回填 A；同一 worker 自动继续重试。not_ready 分支不登记 done、不发 kb:refreshed，且 refresh 的 K:297–301 门阻止未初始化情况下扫描、发布、落盘。

第 50 次连续 not_ready 后，仍在同锁内保留 pending（已有 B 则保留 B）、清 inflight 并将 running=false 后返回。下次触发时，O:1224 的排队同目标提前返回仅适用于 running=true；pending 非空也不会命中 O:1232 的已完成短路，因此可重新启动 worker。成功刷新后 O:1296 清零失败计数；更换目标本身不会清零，计数是 worker 级连续失败次数。

**结论：A not_ready 不再覆盖 B；自动恢复在有限重试窗口内成立，耗尽后保留目标、等待下次触发的行为明确。不能表述为无限期无人触发也必然恢复。**

## P6 关注点

1. **恢复时延与暂停反馈：** 200ms 是失败返回后的轮间休眠；每次 refresh 的 wait_init 自身最多名义等待约 10s。50 次连续失败加 49 次休眠，暂停约在 509.8s 后，线程调度和工作耗时可进一步延长，并非严格墙钟截止。隔离验证慢初始化窗口内自动恢复、A→B→C 保留最新目标、50 次耗尽后同目标重启及线程创建失败恢复；明确暂停状态如何向用户显示。初始化在暂停后才完成，当前仍需新触发。
2. **持久化反馈：** 区分内存刷新成功与磁盘保存成功，明确保存失败的提示和重试；不能用 kb refreshed 日志证明落盘成功。
3. **缓存与容量：** 隔离 v4 PDF/DOCX fixture 验证 49999+2、不可解析缓存自身超额、room=0、容量释放和 incomplete 不升级。旧不可解析块优先全量保留允许总量超过 50000，需明确额度语义并测初始化耗时与内存。
4. **交付与界面：** 核对源码、dist、打包 exe 一致；另行运行窗口验证学科下拉、连续输入/失败后的 TM 保存及“保存上一完成对”语义。PID 17624 本轮无桌面复测结论。
5. **迁移与发布：** 安装升级保留用户数据，验证 Python→Rust→Python 的缓存/TM 续用；沿用长领域名、窄窗、NSIS+zip+SHA256、体积、冷启动及内存验收。说明不解析格式、陈旧缓存和 CSV 子集边界。

本轮无新增必修项；进入 P6 后按上述边界验收。
