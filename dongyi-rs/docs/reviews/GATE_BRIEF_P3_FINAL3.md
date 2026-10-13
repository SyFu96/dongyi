# P3 复审 Brief C（N1/N2 定点）

你是阶段复审人，定点复核『懂译』Python→Rust 重构 **P3** 上一轮报告 `GATE_REVIEW_P3_FINAL2.md` 的两项遗留（无需重做全量审查，定点验证即可）：

## N1（MAJOR）→ 已修
**修复方式（采纳"后端回传 effective_provider"建议）**：
- `src-tauri/src/orchestrator.rs` `on_kind_provider`：`config:updated` 事件在 **Applied 与 Refused（回滚）两分支统一回传 `ori.provider_for(kind)`（即发布/回滚后的真实生效 provider，"ollama"|"openai"）**，不再回传 override 原值（""）。Out::Refused 枚举已删掉不再需要的 `old` 字段。
- `src/App.tsx` `config:updated` 监听：**直接信任 `p.provider` 为生效值**（"openai"→openai，否则 ollama），删除闭包捕获 `provider`（首次渲染值）参与判断的 `followOpenai` 逻辑。
- 复审要求（上轮 N1 建议定点验证两个映射）：
  1. 全局 provider=openai + kind override=""（跟随全局）→ 切 openai 保存失败回滚 → chip 应显示 **openai**（此前 bug 显示 ollama）
  2. 全局 provider=openai + 显式切 ollama 成功 → chip 应显示 **ollama**（override 不再被闭包污染）
- 方法可用上轮同款：从 App.tsx 提取处理代码注入事件验证；或静态证明。**注意前端已删 followOpenai 逻辑，provider 值由后端解析**。

## N2（MINOR）→ 已修
`crates/dongyi-llm/src/lib.rs` `mock_离线重定向零跟随` 尾部 `let _ = server_rx.recv_timeout(6s)` 已改为与另两项 mock 相同的严格 match（Ok(Ok(()))通过 / Ok(Err(e)) panic / Timeout panic）。

## 约束与事实
- 其余上一轮已确认解除项不必重查；用户实测确认（Enter 保留原文/置顶持久/热键主流程）与"chip 不取消在途流"语义继续有效。
- `cargo test -p dongyi-llm` 11 项全绿；`cargo check -p dongyi-rs` 无警告；`npm run build` 通过（本轮遇过一次 Node 0xC0000005 偶发崩溃，重试即过——环境内存不稳，非源码问题，上轮你已见过）。
- 运行 exe 由需求方维护（当前 PID 21216 为最新构建），你**不得启动/重启 exe**。
- 只读分析 + 无副作用构建/测试。

## 产出
报告写 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P3_FINAL3.md`：N1 两映射定点证据、N2 收口确认、新发现（如有，分级）、最终判定 **PASS（P4 可开工）/ FAIL（必修清单）**、P4 关注点（可沿用上轮）。
