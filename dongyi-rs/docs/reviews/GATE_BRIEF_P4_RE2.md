# P4 复审 Brief C（R1/R2 ticket 状态机定点复核）

你是阶段复审人，定点复核『懂译』P4 上轮 `GATE_REVIEW_P4_RE.md` 的两项 MAJOR（R1/R2）。不重审已解除项（N1/N4~N7、ConfigPatch 形状、误报修复等沿用上轮结论）。

## 修复映射

SettingsView（`src/App.tsx` ~934-1024 + footer）状态层整体重构为**统一 ticket 状态机**：

- **R1（保存期间新补丁被清空 / 空保存误标已保存）** →
  `patches` Map 的 entry 增加 `seq`（`set()` 用 `++patchSeq.current`）；save 提交时 snapshot committed（含各自 seq）；成功后**只删除 `cur.seq === entry.seq` 的补丁**（提交后又被改过的同 key 与期间新增 key 都保留）；`patchSeq` 推进；**dirty 由 patches.size>0 决定**（recompute）；保存期间有残留 → 提示「已保存提交的修改；保存期间的新改动尚未保存，可再次保存」，按钮保持可点击（再次保存时 entries 非空）。空保存入口 `patches.current.size === 0` 直接 return。
- **R2（迟到重拉/放弃覆盖新草稿）** →
  **所有覆盖类异步统一 `pullLatest(reset)` 票据入口**：发出时记 `pullId = ++pullId.current` + `editAt = patchSeq.current`；响应回来若 `pullId` 已过期（有更新的重拉）**或 `patchSeq !== editAt`（等待期间发生过编辑）→ 响应整体丢弃，不 setCfg 不清草稿**。使用点：
  1) 挂载初始读取 `pullLatest(false)`；
  2) `config:updated` 广播（SettingsView 自己的监听）：dirty → 仅冲突提示；clean → `pullLatest(false)`；
  3) 「放弃修改」：`patches.clear() + patchSeq++` 后 `pullLatest(true)`——响应到时若期间又编辑则不覆盖，草稿（新 set() 建立）保留。
  另：保存进行中（savingRef）广播监听直接 return（不重拉不提示，保存完成 recompute + 后续广播收敛）；保存 footer 的放弃在 saving 中无操作。
- dirty 一律经 `recompute()`（patches.size>0），不再有旁路 setDirty(true) 后又被全量 clear 的路径。

## 需求方实测
正常单次保存/放弃/×关闭可用，无异常提示（2026-10-13）。R1/R2 属并发反例，不做桌面复现要求。

## 复审方法（定点）
读代码核对上述 ticket/seq 逻辑闭合（重点：save 成功回调与 savingRef/广播/放弃的交叉窗口；pullLatest 的 ticket 判定是否覆盖你上轮提出的全部四个反例：clean 重拉中编辑、自身广播中编辑、放弃等待中编辑、保存中放弃）；跑 `cargo test --workspace --locked` + `npm run build`（偶发 Node/LLVM 崩溃重试即过）；Node 内存定点执行 setIn/save/pullLatest 可选。**只读 + 无副作用构建/测试；禁止启动/重启 exe**；报告写 `D:\划词小工具\dongyi-rs\GATE_REVIEW_P4_RE2.md`。

## 产出
R1/R2 反例逐项闭合证据（行号）；新发现分级；末列 P5 关注点；**PASS（P5 可开工）/ FAIL**。
