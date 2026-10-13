# 懂译 P3 最终定点复审 C（N1/N2）

日期：2026-10-13。**判定：FAIL（P4 暂不得开工）。**

N2 已收口；N1 的前端闭包问题已修，但后端未将显式空串 override 解析为全局 provider，brief 要求的第一映射仍存在反例。必修项为 N1 的空串解析。

## 1. 范围与方法

完整读取 `GATE_BRIEF_P3_FINAL3.md`、`GATE_REVIEW_P3_FINAL2.md`，仅复核 N1/N2。核对当前磁盘源码，并为判断空串配置是否会被归一化，定点补读配置加载、保存入口。其余已解除事项沿用上轮结论，不做全量重审。

只读分析、内存中的前端事件注入及 loopback mock 测试；未修改业务源码或真实用户配置，未调用真实云端模型，未启动/重启产品 exe、未操作桌面。本轮仅新增本报告。brief 中当前 PID/最新构建的陈述未独立核验，不作为源码结论依据。

## 2. N1（MAJOR）：部分修复，空串回滚未闭合

### 实际代码

- `src-tauri/src/orchestrator.rs:1007`：Refused 已移除 old 字段。
- `:1017`：切回跟随全局时删除 kind 字段；`:1032` 保存失败不发布候选配置；`:1038` 保存成功才发布。
- `:1044`：Applied/Refused 共用事件分支；`:1047` 调用 `ori.provider_for(kind)`，`:1050` 回传其结果。
- **关键缺口在 `:131–138`**：`as_str().map(str::to_owned).unwrap_or_else(...)` 只对缺失/非字符串 fallback。JSON 字符串 `""` 的 `as_str()` 返回 `Some("")`，故结果仍为 `""`，不会跟随全局。因此“后端恒发 ollama|openai”的注释并不成立。
- `src/App.tsx:281–287`：已删除 followOpenai，直接将 openai 映射为 openai，其余映射为 ollama；后端若发空串，chip 仍显示 ollama。
- `src/App.tsx:110–113` 初始加载明确将空串视为跟随全局；`crates/dongyi-core/src/lib.rs:125–150` 加载配置未过滤空串，`:155–162` 保存也未过滤。该状态并非由源码保证不可达。

### 两映射定点证据

| 场景 | 后端推导及事件 | 前端实际结果 | 结论 |
|---|---|---|---|
| 全局 openai，kind override 为显式 `""`；切 openai，key 已配置，保存失败 | old 空串，cand 为 openai；失败保留 guard 中空串；provider_for 返回空串；事件 provider=`""` | input/chat 均为 ollama，期望 openai | **FAIL** |
| 全局 openai，kind 字段缺失；切 openai 保存失败 | 未发布候选；provider_for 对缺失字段 fallback 为 openai | input/chat 均为 openai | PASS，但不能替代显式空串场景 |
| 全局 openai，显式切 ollama 保存成功 | cand 写入 ollama 并发布；provider_for 返回 ollama | input/chat 均为 ollama，期望 ollama | **PASS** |

从实际 App.tsx 提取完整 `config:updated` 注册块，使用项目 TypeScript 转译，在 Node 内注入 reg/setter；对 input/chat 各注入 openai、ollama、空串三种事件，实测结果分别为 openai、ollama、ollama。未生成额外测试文件。后端失败/成功分支及 `Option` 空串行为采用静态证明；没有实际制造用户配置写盘失败，不宣称桌面端到端复现。

上轮报告将“字段缺失”的旧值也记作空串，因为 on_kind_provider 的 old 使用 `unwrap_or("")`。本轮明确区分缺失字段与 JSON 中显式空串：前者已修，后者仍失败。brief 明确要求空串跟随全局，现有加载/保存入口也未建立“空串必删除”的约束，不能仅凭常规 chip 写入会删除字段而放行。

**必修建议：** 在 provider_for 的 fallback 前过滤空串，例如 `.as_str().filter(|s| !s.is_empty())`，再解析全局 provider。保留前端直接使用生效值的修复。定点验证上述显式空串失败回滚与显式 ollama 成功两映射即可，无需扩大全量测试。

## 3. N2（MINOR）：已解除

`crates/dongyi-llm/src/lib.rs:1058–1062` 已严格检查服务端结果：仅 `Ok(Ok(()))` 通过；`Ok(Err(e))` panic；`Err(_)` panic，覆盖 Timeout 和 Disconnected。Disconnected 的提示也写作“超时”，属于诊断措辞，未吞失败，不列为阻断缺陷。

`:837–854` 的 helper 将线程 panic 转为通道 Err；`:1017` 的断连断言现在必须通过最终收口。`:1049–1055` 保留 Failed(307) 与目标端口零连接断言。

实际执行 `cargo test -p dongyi-llm --locked mock_离线重定向零跟随 -- --nocapture`：退出码 0，**1 passed，10 filtered out**。此前带 `--exact` 的命令因缺少 `tests::` 前缀只运行 0 项，未计作通过证据；随后已正确执行目标测试。没有重跑全量构建或 11 项测试；brief 所述全绿/构建结果属于需求方提供的信息。

有界 recv_timeout 保证主测试等待结果超时即失败，不代表 worker 线程自身必然终止。

## 4. 新发现、判定与必修清单

**FAIL。P4 暂不得开工。** N1 仍为 MAJOR：显式空串 override 的后端生效值解析未闭合，导致回滚后的 chip 错误显示本地。这是 N1 遗留的具体边界，不另增缺陷编号。N2 已解除；本次定点范围内未发现其他新缺陷。

必修：修正 provider_for 对显式空串的全局 fallback，并提供两映射证据。无需重做 Enter/置顶/热键实测；保持 chip 切换不取消在途流的既定语义。

## 5. P4 关注点

- 设置页与 chip 共用实际配置解析和保存事务；统一缺失/空串跟随全局、显式本地/云端与失败回滚语义。
- 保持请求身份、检索代次、终态清缓冲及解释惰性派发顺序。
- 后续只补有价值的确定性用例：EOF 截断、旧 chat 终态隔离、拒绝替换及可控时钟 warm 让位；不夸大现有测试覆盖。
- 保留 Enter 原文、跨会话置顶、不抢焦点及交互标签激活；前端交付须重建产品 exe，运行实例仍由需求方维护。
- 沿用 P2 混合 DPI、PDF/终端、富格式剪贴板恢复的证据边界；静默划词限制继续按需求方弃审处理。
