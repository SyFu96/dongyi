# 懂译 P5 定点复审 C

日期：2026-10-13。**判定：FAIL；P6 暂不放行。**

RE-M2、RE-M3 和三条 MINOR 的指定反例闭合；RE-M1 的超时门已补上，但初始化幂等及未就绪回填仍有两处 MAJOR 竞态。测试全绿不能排除这些线程交错。

## 范围与验证边界

以 `GATE_REVIEW_P5_RE.md` 的三个 MAJOR 反例及 m2/RE-m1/RE-m2 为范围，仅核查对应源码和调用链，不重新审查已通过的全部 P5 项目。K/O/A/G/D 分别指 `crates/dongyi-knowledge/src/knowledge.rs`、`src-tauri/src/orchestrator.rs`、`src/App.tsx`、`crates/dongyi-knowledge/src/glossary.rs`、`crates/dongyi-knowledge/src/domains.rs`；行号取当前磁盘源码。

使用 env-list 技能核对环境。未启动、重启、终止或替换产品 exe，未操作 PID 20228，未调用真实模型或桌面 IPC，未改业务源码和真实配置、TM、KB。构建会更新正常 target/dist 产物，新增项目文件仅本报告。

| 验证 | 本轮结果 |
|---|---|
| `cargo test --workspace --locked` | 退出码 0；capture 1 + core 4 + knowledge 15 + LLM 11，共 31 项通过；壳层/trigger/doc-tests 无测试。 |
| `npm run build` | 退出码 0；tsc + Vite 通过，19 modules，Vite 18.59s。 |
| 实际前端函数 | 从 App.tsx 的 TypeScript AST 提取 computeDomains，转译后在 Node VM 执行。Battery/battery 均启用取 Battery；Battery 停用取 battery；跨组 `- / 0 / Z / _ / a` 顺序正确，非法中文 id 被过滤。三个用例通过。 |
| CSV 补充执行 | 提取实际 Rust 函数编译临时 harness 的命令被工具策略拦截，未执行；不计为测试通过。以下两个新增 CSV 边界结论来自源码状态机推演。 |
| 初始化超时/额度/替换故障 | 本轮为源码及线程交错推演，没有做超时注入、50000 块 fixture、线程创建故障注入或断电实测。既有 PDF fixture 仍只有一个 PDF 块，不能冒充额度边界覆盖。 |

## 六项逐点核验

### RE-M1：未完全闭合 / MAJOR

**已修部分：** K:264–287 的 wait_init 返回 bool，未就绪直接返回 not_ready，早于扫描、内存发布和落盘。因此“初读超过约 10s，refresh 将空 Store 当成已就绪覆盖旧盘”的原直线路径已阻断。K:184–210 使用独立 init_running，spawn 失败复位并可由 wait_init 再触发；O:1276–1282 不更新 done、不发送刷新完成事件，退出时清 running。10s 是 500 次 sleep 的名义等待量，不能理解为严格墙钟截止时间。

**必修 C-M1：start_init 的就绪检查与 CAS 存在间隙，仍可能二次初始化覆盖刷新结果。** 证据 K:179–202、267–269。

合法交错：第一次 init 正在读取；refresh 的 wait_init 进入 start_init，在 K:180 读到 init_done=false 后被抢占；第一次 init 发布旧索引，并依次写 init_done=true、init_running=false；被抢占的调用恢复，K:185 CAS 成功，启动第二次 init。wait_init 随后看到 done=true，允许 refresh 继续。第二次 init 可以先读取旧 index，稍后在 K:196–199 无条件写回；期间 refresh 已发布新 files/chunks，故新内存索引被旧快照覆盖，或刷新持久化时重新取到旧快照。SeqCst 只保证原子操作顺序，不能把检查和 CAS 合成一次事务。

**修复要求：** 成功抢到 init_running 后再次检查 init_done；若已就绪，复位运行标志并返回，不 spawn、不再读盘发布。或用单一状态机/锁保证完成态不再进入初始化。必须核验上述指定交错。

**必修 C-M2：not_ready 回填无条件覆盖较新的 pending。** 证据 O:1235、1262–1265、1276–1282。

合法交错：worker 取 A，inflight=A，等待初始化；此时目录配置改为 B，maybe_refresh_kb 将 pending=B（worker 仍 running）；A 超时返回 not_ready，O:1280 无条件写 pending=A，丢失 B。若没有新的 KbCheck/领域触发，B 不会被消费；后续刷新可能继续处理旧目录集合。这违背原单 worker 的“最新目标保留”要求，也使 RE-M1 的目标重试不可靠。

**修复要求：** 同一调度锁内，仅在 pending 为空时回填失败目标；已有较新目标应保留。明确退出后的触发机制，核验 `inflight=A → pending=B → A not_ready` 后 pending 仍是 B。初始化成功本身当前不会自动启动刷新，因此不能声称无需后续触发即可恢复。

### RE-M2：指定反例闭合

K:326–359 先处理不可解析文件，全部旧块进入 new_chunks，不使用 room；complete 只继承旧记录（缺记录为 false），不会把旧 incomplete 升级为完整。K:358–387 随后对可解析文件使用 saturating_sub 和 room 截断。

逐点推演：

- `a.txt=49999 块 + b.pdf=P1/P2`：先保留 P1/P2，txt 只取 49998，总计 50000；PDF 尾块不会丢失。删除 txt 后仍保留 P1/P2。
- 不可解析缓存达到 50000 块，或超过 50000：所有 PDF/DOCX 旧块先保留；room=0 仅跳过可解析文件。其后释放容量，可解析文件因未入册或 incomplete 而重建补齐。
- 旧 PDF/DOCX complete=false：全量保留现有短缓存且仍为 false；不能恢复上轮已实际丢失的尾块，但不会继续误标完整。

PDF 与 DOCX 走同一不支持扩展分支。结论限于扫描中仍存在、元数据可读且未被 20MiB 文件过滤排除的文件，沿用上轮范围。此等价保真策略允许总缓存及检索统计超过 50000，不能继续宣称全索引严格封顶 50000；应在 P6 明确容量语义并评估内存。以上是代码推演，既有测试没有实际覆盖这些额度反例。

### RE-M3：指定反例闭合

K:413–427 先写同目录 tmp，再直接 fs::rename(tmp,target)；无先 remove_file 的窗口。tmp 写失败和 rename 失败均有日志，失败路径不主动删除正式索引。

Rust 官方文档明确 rename 会替换已存在目标，Windows 使用 MoveFileExW 并有平台回退实现：[std::fs::rename 官方说明](https://doc.rust-lang.org/std/fs/fn.rename.html)。因此该修正满足上轮“保留旧正式文件直到平台替换成功”的要求；不是断电耐久性实测，也没有证明写入已经刷到物理介质。

持久化错误仍只记日志，refresh 返回普通统计，O:1287 仍标 done；这是既有内存成功、磁盘失败的策略，需在 P6 明确重试与界面反馈。不能把 kb refreshed 日志解释为落盘成功。此限制不重新判为上轮先删后改的 RE-M3。

### m2：闭合

A:70–76 组内及组间均用 idCmp 的 `<`/`>`；合法 id 仅 ASCII，顺序与 D:73、81 的 Rust 字节序相同。实际函数三个定点用例通过，上轮 Battery/battery keeper 分歧消除。

### RE-m1：指定反例闭合

O:1224–1231 只在 running 时因 pending/inflight 同目标提前返回；O:1249–1251 spawn 失败清 pending、复位 running。因此原 `spawn 失败 → pending=S → 下次 S 提前返回` 不再成立，下次可重启。该结论来自代码推演，未注入系统线程创建失败。not_ready 保留 pending 时也因 running=false 可再次启动，但存在上面的 C-M2 最新目标覆盖问题。

### RE-m2：指定反例闭合

G:28、45–47、61–63 的 field_started 使引号仅在字段起始开启；`SOH,state"of health,note\nBMS,系统\n` 中内部引号作为普通字符，LF 正常结束第一条记录，BMS 不再被吞。G:53–59 使孤立 CR 结束 record，CRLF 只结束一次；`SOH,健康度\rBMS,系统\r` 得到两条记录。引号内部在 G:31–42 保留 CR/LF，双引号转义继续生效。仅判断上轮指定 CSV 子集边界，不宣称完整 CSV 标准兼容。

## 放行条件与 P6 关注点

**本轮 FAIL 的必修项为 C-M1、C-M2，均位于 RE-M1 恢复链。** 定点修正并核验两个指定交错后再复审，不需要重做全部已通过 P5 项目。

P6 关注点：

1. 明确未就绪后的重试触发；持久化失败应可辨认，明确是否重试，区分内存刷新成功与磁盘保存成功。
2. 用隔离 v4 PDF/DOCX fixture 核验 49999+2、不可解析缓存自身超额、room=0、容量释放及 incomplete 不升级；说明新额度语义，关注大量旧缓存的内存和初始化耗时。
3. 源码、dist、打包 exe 一致；在另行允许的运行窗口验证学科下拉、连续输入/失败后的 TM 保存及“保存上一完成对”的界面语义。当前运行进程没有桌面复测结论。
4. 安装升级保留用户数据；验证 Python→Rust→Python 的缓存/TM 续用，说明不解析格式、陈旧缓存、CSV 子集、刷新及落盘失败行为。
5. 沿用上轮长领域名、窄窗、NSIS+zip+SHA256、体积、冷启动和内存验收要求；构建通过不等于这些验收完成。
