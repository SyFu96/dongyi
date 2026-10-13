# 懂译 P4 第三次定点复审报告（D）

日期：2026-10-13。**最终判定：PASS，R3／MAJOR 解除，P4 本次定点门禁通过，可进入 P5。**

## 范围与验证边界

读取前轮 `GATE_REVIEW_P4_RE2.md` 与当前 `src/App.tsx`，仅复核唯一阻断项 R3 的四点及放弃等待中保存的交叉窗口；此前已解除项沿用前轮结论，不做全量重审。

未操作 PID 56408，未启动、停止或重编产品 exe，未调用真实 IPC、修改真实配置或业务代码。仅新增本报告。以下行号对应本次磁盘源码。

使用项目 TypeScript AST 提取实际 `setIn`、`recompute`、`set`、`save`、`pullLatest` 与放弃按钮 `onClick`，转译后注入状态 stub、受控 Promise，执行确定性内存检查。首次检查因 PowerShell 管道中的中文匹配未提取到按钮而在前置断言终止；改用 `pullLatest(true)` 识别 AST 属性后，五条检查全部通过，Node 退出码 0。`tsc --noEmit` 通过。未重复无关 Rust 测试或全量构建。

该验证覆盖实际函数的局部状态转换，不代表 React 桌面端到端实测、真实 IPC 或运行实例与源码一致。

## R3 定点核验

| 核验点 | 代码证据与受控顺序 | 结论 |
|---|---|---|
| 放弃失败后草稿仍可保存 | :1170–1173 仅守卫后调用 `pullLatest(true)`，不预清补丁或推进编辑代次。编辑 theme=light → 放弃 → 读取拒绝；:968 只置错误提示。确认 cfg=light、Map 有补丁、dirty/dirtyRef=true；随后保存实际提交 theme=light，成功后 Map 空且 dirty/dirtyRef=false。 | PASS |
| 放弃等待中编辑不被覆盖 | :956 记录编辑代次，:995 编辑推进代次；:959 在任何覆盖或清空之前验证票据。放弃等待中再编辑同路径为 new → 旧读取返回 disk；确认 cfg 与补丁仍为 new，dirty/dirtyRef=true。 | PASS |
| 放弃成功后 dirty 与 Map 一致 | :959 票据有效才进入 :960–965，同一同步回调内 setCfg、clear、推进代次、recompute、清提示，无 await 插入窗口。有效读取返回 disk 后，cfg=disk、Map.size=0、dirty/dirtyRef=false、msg=null；等待期间也保持 dirty 与 Map 一致。 | PASS |
| 保存中放弃仍无操作 | :1002 在保存 IPC 前置 savingRef=true，:1022 finally 解锁；:1170 在重拉前直接返回。保存在途点击放弃，确认无新增 get_config、补丁和编辑代次未变。 | PASS |

**附加交叉窗口：PASS。** 放弃等待中允许保存；保存成功 :1007 推进 patchSeq，使先前放弃读取的 editAt 失效。受控顺序为编辑 light → 放弃读取在途 → 保存成功 → 旧放弃响应返回 stale；确认 cfg 仍 light、Map 空且 dirty/dirtyRef=false，旧响应未覆盖。

请求发出时无需额外推进 patchSeq：:955 推进 pullId 已使更早读取失效；patchSeq 用于识别编辑与保存完成。此次删除两行不会丢失旧读取保护。失败分支不动补丁，前轮 dirty=true／Map 空／保存直接返回的死态已闭合。本次范围未发现新的放行阻断项。

## P5 关注点

- RAG、术语表、翻译记忆兼容既有 Python 数据格式与同一份数据文件；新增字段遵守差异提交与未知字段保留。
- 保存成功才发布；kind 缺失／空串跟随全局、失败回滚、切 chip 不取消在途流保持一致。配置读取、编辑、放弃及广播保持统一代次与失败恢复；明确保存期间忽略广播后的刷新策略，不能假定没有后续广播时必然收敛。
- 保持请求身份、检索代次、关闭／停止作废及解释惰性，防止旧结果进入新会话。
- 索引、文件解析、模型查询放在后台；保留输入原文、last_target retry、跨会话置顶和不抢焦点。
- 正式交付须重编产品 exe，分别记录源码、构建与运行实例证据；混合 DPI、PDF／终端、富格式剪贴板按既有边界验证，不重开静默划词浮标弃审限制。本次未动现有运行实例。
