# P4 Gate 复审 Brief

你是阶段复审人，审查『懂译』Python→Rust 重构 **P4 阶段**（设置 GUI + 主题 + 语向选择）。

## 背景（必读）
- 执行文档：`D:\划词小工具\Rust重构执行文档.md`（§5 架构、§7 坑清单、§10 已知限制、§11 阶段记录）
- P3 闸门报告链（约束延续）：`GATE_REVIEW_P3_FINAL4.md`（**PASS**）与 `GATE_REVIEW_P3_FINAL2/3.md` 的 P4 关注点：
  1) 设置页与 provider chip 共用同一实际配置解析与保存事务（缺失/空串=跟随全局、显式本地/云端、失败回滚语义一致）
  2) 保持请求身份/检索代次/终态清缓冲/解释惰性派发顺序（不得重新引入 on_tab pre-insert 吞请求回归）
  3) 保留 Enter 原文、跨会话置顶、不抢焦点；前端交付须重建 exe（frontendDist 编译期内嵌）
  4) chip 不取消在途流是用户明确语义；弹窗开着静默划词浮标不显示=需求方弃审的已知限制
- P3 实测已确认通过的用户语义：输入翻译 Enter 保留原文、置顶跨会话保持（popup:pin 回放）、主流程热键。

## P4 交付物（本轮审查对象）
1. **设置页 GUI**（`src/App.tsx` SettingsView + `src/index.css` 表单组件类 + `src-tauri/src/lib.rs` 窗口改动）：
   - 无边框自绘标题栏（data-tauri-drag-region + × 隐藏），inner_size 820x620
   - 左导航（01 模型 / 02 划词 / 03 热键 / 04 检索 / 05 外观，彩色编号块）+ 右表单卡片 + 底部保存条（dirty 状态 / 放弃修改 / 已保存提示）
   - 弱类型整份保存（未知字段如 domains/tm_enabled/blacklist_processes 必须保留，CSetValue/setIn 不可变路径写）
2. **api_key 粘贴框**：password + 显示切换（cloud.api_key 与 web_search.api_key 各一处）
3. **主题跟随系统**：config.theme（auto/light/dark，旧值 dark 直接可用）→ `useThemeSync`（App 顶层每个窗口实例）={
   get_config 读取 → html.dark；auto = matchMedia(prefers-color-scheme) 跟随系统；
   `save_config` 命令成功后广播 `config:updated{kind:"",provider:"",theme}` → 三窗口即时切换
   }。注意 kind 空串不得误触发 provider-chip 监听（其 handler 按 kind===chat/input 过滤）。
4. **输入翻译语向**：TARGET_LANGUAGES 13 项（Python popup.TARGET_LANGUAGES 原值集）→ InputView select；
   提交 `input_translate{text,target}`（auto→null）→ AppEvent::InputAsk{text,target}（target 空=自动中英互译，
   非空=Python `_input_prompt` 的专属语向 prompt）→ 会话记录 last_input/last_target → retry 回放语向。
5. **实测后修复（需求方确认可用）**：
   - × 关闭改走 Rust 命令 `hide_settings`（Web 端 window API 需 capabilities 许可，未放行）
   - 「本地模型名」改下拉：`dongyi_llm::ollama_models(base_url)`（GET /api/tags，blocking 客户端、3s/5s 超时、
   失败返回空 vec）+ tauri 命令 `local_models`（读 SharedCfg["base_url"]）；前端 ModelSelect：列表空/失败退化为手输+提示，当前值不在列表时以占位 option 保留

## 实测确认（需求方 2026-10-13）
设置页可用、× 可关、api_key 粘贴可用、主题跟随可用、🌏 语向选择可用、本地模型下拉列全。chip 不取消在途流语义继续有效。

## 复审方法
读代码核对上述每项（证据行号）；跑 `cargo test --workspace --locked` 与 `npm run build`（注意：机器内存偶发不稳，
LLVM/Node 可能偶发崩溃，重试通过即有效，不判源码缺陷）；静态审查新引入面：
- save_config 广播回环（设置窗自身也收事件，chip/theme 状态一致性；保存意图事件与 on_kind_provider 事务事件的相互作用）
- 弱类型保存是否可丢未知/多余字段（setIn 分支克隆正确性）
- ollama_models 的 blocking 调用跑在 tauri sync command 线程（验证不会阻塞主线程/UI）
- InputAsk target 贯通（on_input_ask prompt 组装、retry、输入热键 fresh open 的 last_target 清理）
- 设置页「热键重启生效」提示与 trigger crate 概念固定注册的事实一致
- SettingsView dirty/保存/放弃的状态机（并发保存、保存失败后 state）
- 其他 P4 面上可推导反例

## 约束
只读分析 + 无副作用构建/测试；禁止启动/重启 exe（运行中的应用占锁、禁动用户桌面）；产出写唯一文件
`D:\划词小工具\dongyi-rs\GATE_REVIEW_P4.md`。

## 产出要求
每交付项证据行号 + 结论；新发现按 BLOCKER/MAJOR/MINOR 分级（文件:行号/原因/修复建议）；末列 P5 关注点；最终判定 **PASS（P5 可开工）/ FAIL（必修清单）**。
