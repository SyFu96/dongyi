# 懂译 P3 定点复审 D

日期：2026-10-13。**判定：PASS（P4 可开工）。**

本轮仅复核 FINAL3 中 N1 的显式空串 fallback 修复及两项映射。N1 已解除；N2 和其他已解除事项沿用上轮结论，本轮范围内无新增阻断项，无必修项。

## 修复与事务证据

- `src-tauri/src/orchestrator.rs:131–140`：`provider_for` 在 `as_str()` 与 `map(str::to_owned)` 之间增加 `.filter(|s| !s.is_empty())`（第 136 行）。显式空串由 `Some("")` 变为 `None`，与缺失字段一样进入全局 provider fallback；非空 `ollama` 不被过滤。
- `:1017–1041`：候选配置由 guard 克隆；保存失败（第 1034–1037 行）只产生 Refused，不赋值 guard；保存成功才在第 1040 行发布候选配置。失败回滚仍保留原始显式空串，不依赖删除空串或配置加载归一化。
- `:1044–1052`：Applied 与 Refused 共用分支，在事务锁释放后调用 `ori.provider_for(kind)`，以生效值发出 `config:updated`。
- `src/App.tsx:281–287`：事件值 openai 直接映射为 openai，其余映射为 ollama；input/chat 分别更新对应 setter，不依赖首次渲染捕获的全局 provider。

## 两映射定点证据

| 场景（input/chat 均适用） | 后端配置与事件推导 | 前端 chip 证据 | 判定 |
|---|---|---|---|
| 全局 openai，override 为 JSON 显式 `""`；切 openai，key 已配置，保存失败 | 候选 override=openai，写盘失败不发布；guard 仍为显式空串；filter 将空串排除，fallback 返回全局 openai；事件 provider=openai | 注入实际事件处理块：input→openai、chat→openai | PASS |
| 全局 openai，显式切 ollama 保存成功 | 候选 override=ollama，成功发布；filter 保留非空 ollama，provider_for 返回 ollama；事件 provider=ollama | 注入实际事件处理块：input→ollama、chat→ollama | PASS |

第一场景的 old 为 `""`、new 为 `openai`，因此不会被 Out::Same 短路；key 已配置时能够到达保存失败分支。第二场景的显式 ollama 优先于全局 openai，不会被新过滤误伤。缺失字段继续 fallback 全局，不构成回归。

实际从当前 `src/App.tsx` 提取完整 `config:updated` 注册块，使用项目已有 TypeScript 转译，在 Node 内存中注入 reg 与两 setter，对 input/chat 各验证 openai、ollama 两个事件。四个断言全部通过，命令退出码 0。未复制重写前端映射逻辑，未生成测试文件。

## 证据边界与后续

后端 Option/filter 行为、事务失败与成功分支采用当前源码静态证明；前端映射采用实际代码执行验证。未实际制造用户配置写盘失败，不宣称桌面端到端复现，也未独立核验运行 exe 与源码的构建对应关系。用户说明 PID 60608 为最新构建；本轮未操作该进程，未启动/重启产品、未修改业务源码或真实配置、未调用云端模型，未重跑全量构建或无关测试。仅新增本报告。

**最终 PASS。** FINAL3 的唯一必修项已闭合。P4 继续关注设置页与 chip 的缺失/空串跟随全局、显式覆盖及保存失败回滚语义一致性；其他关注点与既定证据边界沿用 FINAL3。
