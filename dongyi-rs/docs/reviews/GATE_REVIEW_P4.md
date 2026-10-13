# 懂译 P4 阶段审查报告

日期：2026-10-13。**判定：FAIL（P5 暂不得开工）。**

指定构建及现有测试均通过，但配置跨窗口一致性、保存状态机及模型查询线程存在四项 MAJOR，必须修复。需求方的正常路径实测结论保留，不足以排除下列边界反例。

## 1. 范围、方法与证据边界

完整读取 GATE_BRIEF_P4.md、GATE_REVIEW_P3_FINAL2.md、GATE_REVIEW_P3_FINAL3.md、GATE_REVIEW_P3_FINAL4.md，以及父目录 Rust重构执行文档.md（包括 §5/§7/§10/§11）。P3 最终以 FINAL4 PASS 为准；FINAL2/3 的失败为已整改历史，不能追溯当作当前失败。核对前端、壳层、编排、core、LLM、trigger 和 Python 语向/提示词基线。下列行号对应本轮磁盘源码。

仅只读分析、允许的构建/测试及 Node 内存定点检查；未启动/重启产品 exe，未操作桌面、真实配置或真实模型服务，未修改业务源码。唯一审查文档产出为本文件；dist/target 是指定构建的正常产物。Cargo 启动的是测试程序，不是应用实例。未独立核验运行中 exe 与当前源码一致，也未进行桌面端到端验证。

| 验证 | 本轮实际结果 |
|---|---|
| cargo test --workspace --locked | 首次通过，退出码 0；构建 26.40s；capture 1、core 4、LLM 11，共 16 项通过；壳层、trigger 和 doc-tests 为 0 项。 |
| npm run build | 首次通过，退出码 0；tsc + Vite 8.3.4，19 modules，Vite 15.73s。 |
| 前端定点检查 | 从实际 App.tsx 提取 setIn、完整 config:updated 注册块、save 闭包，使用项目 TypeScript 转译后注入 stub；退出码 0。未知字段/分支不可变断言通过；整份保存不刷新 chip、保存期间新编辑被清 dirty 的反例成立。未生成额外测试文件。 |
| 快照覆盖反例 | 依据实际读取一次、整份替换和 chip 写候选事务，执行内存中的同构事务序列确认字段丢失；属于静态模型验证，不是实际 Rust IPC 或写盘复现。 |
| 线程核对 | 查本机锁定依赖 tauri-macros 2.7.2 的 wrapper.rs（默认 Blocking:50；分派:242–246；同步直接调用:424–428），并核对 Tauri 官方命令文档。未制造 UI 卡顿实测。 |

现有 16 项测试没有覆盖 SettingsView 保存竞态、三窗配置同步、local_models 线程或输入语向重试，不能据全绿认定这些路径已验证。

## 2. 交付项逐项核对

| 交付项 | 代码证据与结论 |
|---|---|
| 设置窗尺寸、无边框、标题栏、关闭 | src-tauri/src/lib.rs:239–248 设置窗 820×620、decorations(false)；src/App.tsx:978–990 自绘标题栏、data-tauri-drag-region、× 调用 hide_settings；壳层:98–102 隐藏窗口。**基本实现通过**，不销毁窗口；接受需求方可关闭实测。 |
| 左导航、表单卡片、底部保存条 | App.tsx:940–946 五组编号/颜色；:992–1019 左导航与右卡片；:1117–1131 dirty/放弃/已保存提示。index.css:91–117 输入及 select 样式。**结构通过，保存状态机不通过（N3）**。 |
| 弱类型整份保存与未知字段 | App.tsx:917、929–937 Cfg/setIn 分支展开复制；:963–970 路径更新后原对象整份提交；core/src/lib.rs:155–163 序列化整份 Value。内存执行确认 domains、tm_enabled、blacklist_processes 与 cloud 的额外兄弟字段保留、原分支未改。**单一快照编辑通过；并发后的最新字段无法保留（N2）**。 |
| 两处 api_key 粘贴框 | App.tsx:1044–1045 cloud.api_key；:1097–1098 web_search.api_key；:1211–1228 受控输入、password/text 切换、autoComplete off。**通过静态核对，接受需求方粘贴实测**。 |
| auto/light/dark 三窗主题 | App.tsx:79–138 读取、归一化、html.dark、matchMedia change、保存广播监听和卸载清理；:146–149 每个窗口顶层调用；:1234–1249 三选；index.css:10–48 双主题变量；壳层:37–51 成功保存后广播 kind/provider 空串及 theme。**正常主题链通过**；设置窗收到广播只更新主题，不重提 save_config，不存在由此触发的保存回环。初始化竞态见 N7。 |
| kind 空串过滤与 chip 状态 | App.tsx:377–383 handler 仅更新 chat/input，所以空 kind 不误改 chip；但没有另一个全量更新 handler。**过滤通过，保存后的整体配置/chip 一致性不通过（N1）**。 |
| 13 项输入语向 | App.tsx:53–67 与 Python 划词小工具/popup.py:960–974 的 13 项逐项一致（auto 是 None 的 UI 标识）；:820、836–845 select；:859 提交。**值集通过**；auto 在此转换为空串，故父层:416 的 auto→null 分支实际未被此路径使用。空串经 IPC 到编排仍表示自动，当前语义正确，不列功能缺陷。 |
| target IPC、prompt、retry、fresh open | 壳层 lib.rs:139–143 target Option 转默认空串；编排:45、304 消费 InputAsk；:942–963 存 last_input/last_target 并按空/非空组 prompt，与 Python app.py:541–545 一致；:989–996 重试使用原 target；:524–537 新会话清 last_target；:840–855 输入热键 fresh open 调 begin_session，已开仅切标签。**贯通通过静态核对**。 |
| 本地模型获取 | LLM lib.rs:128–147 GET /api/tags，连接 3s/总请求 5s，解析 names，传输/解析失败空 vec；壳层:108–116 读 SharedCfg base_url，HTTP 前释放锁。**请求/解析主体通过，线程要求不通过（N4）**；未检查 HTTP 状态码，通常错误 JSON 没有 models 会退空，不能宣称所有非 2xx 必退空。 |
| 模型选择退化与占位 | App.tsx:1172–1207 异步获取、卸载保护、空/失败时手输、当前值不在列表时显示原值占位，不自动改 cfg。**保留旧值通过，空 vec 分支未显示提示（N5）**。 |
| 热键重启提示 | App.tsx:972、1077 提示重启生效；编排:226–229 在启动时 parse_hotkey；trigger/src/lib.rs:77–114 解析描述、:120–125 将 specs 固定给钩子线程。**与固定注册事实一致**；非动态热更新。 |

## 3. P3 延续约束

- 实际 provider 解析仍正确：编排:133–142 缺失/显式空串跟随全局，非空覆盖优先；App.tsx:198–209、263–276 初次/新会话映射一致。编排:1034–1059 与壳层:40–43 均在同一 SharedCfg 锁内保存成功才发布，失败保留旧内存。**单次事务失败回滚通过**，但同锁只能序列化写入，不能防止旧快照覆盖，也不能代替全窗口通知（N1/N2）。
- 请求隔离保留：编排:398–453 同 kind 检索撤销绑定、epoch/sgen 双门；:505–516 登记请求身份；:1084–1097 迟到事件先检查；App.tsx:281–336 req_id 门控，终态先清缓冲；:345–357 Stop/reset 清绑定。**本轮未发现重新引入相应回归**，不声称已有自动测试全覆盖。
- 解释惰性：编排:880–895 仅判断/清 failed 后 dispatch_request，没有 on_tab pre-insert requested。**通过**。
- Enter 保留原文：App.tsx:853–860 提交不清 draft；置顶跨会话：编排:524–537 不清 pinned、:829–830 回放；前端:260–261、popup:pin 监听保留原语义。无焦点默认仍由壳层:223–225 维持，交互标签由编排:881–882 动态激活。**沿用实测与静态证据**。
- 编排 on_kind_provider:1020–1080 未取消 LLM，在途流不因 chip 切换中断；**符合用户明确语义，不列缺陷**。
- 弹窗开着静默划词浮标不显示继续是需求方弃审的已知限制。frontendDist 为 tauri.conf.json:8 的 ../dist，壳层:275 generate_context 编译期嵌入；**前端正式交付须重编应用 exe**。本轮只执行指定测试/前端构建，不替换运行实例。

## 4. 新发现与修复建议

### N1／MAJOR：整份保存不刷新当前弹窗的后端、模型名及 key 状态

**证据：** App.tsx:198–212、263–278、377–383；src-tauri/src/lib.rs:44–49。

弹窗配置只在挂载和 popup:open 拉取；全量保存广播 kind=""，chip handler 不处理，模型名、全局 provider、cloudKeyOk 也不更新。例如当前 popup 打开、input/chat override 缺失或空串、全局为 ollama；在设置改全局 openai 并成功保存（key 已配置），后端 provider_for 已返回 openai，但两 chip 仍显示本地，下个提交实际走云端。修改模型/key 同样不能即时刷新当前弹窗。实际注册块执行已确认空 kind 不触发 setter；这是正确过滤带来的同步缺口，不能简单去掉 kind 过滤。

**建议：** 为整份提交增加明确的配置刷新事件处理，重拉最新配置或携带完整生效快照/版本；用统一映射更新 provider、两种 override、模型名、有效 key 状态，保持 kind 事务事件映射和失败回滚。切换配置仍不取消在途流。

### N2／MAJOR：设置窗长期旧快照覆盖 chip 成功事务，丢最新配置

**证据：** App.tsx:950–959、968–971；src-tauri/src/lib.rs:40–42、99–102；编排:1034–1059。

SettingsView 只挂载读取一次；hide_settings 隐藏而不卸载，且无 config:updated 配置监听。可串行复现的反例：设置窗先持有 kind_providers.input 缺失的快照；用户在 popup 成功切 input=openai；随后设置只改 theme 并保存，旧整份快照覆盖 SharedCfg，input override 被删除。前端 chip 仍显示 openai，因为整份保存空 kind 未刷新它；下个请求可能回到本地。这里不需要同时写盘，互斥锁正确也无法解决。重开设置同样继续持有旧快照，可能显示“配置与磁盘一致”但实际不同；未知字段在快照建立后新增/变化也可能丢失。

**建议：** 保存引入配置版本/比较并交换，冲突显式提示；或向当前配置应用用户改动路径并保留最新未编辑字段。设置窗 clean 时接收最新快照，dirty 时保留草稿并识别冲突；不要无条件用广播覆盖用户草稿。刷新/合并仍应进入同一保存成功才发布的事务。

### N3／MAJOR：保存期间的新修改误标已保存，允许并发保存/放弃互相干扰

**证据：** App.tsx:963–975、1123–1131。

save 捕获提交时 cfg；await 完成后无条件 setDirty(false)。没有 saving、提交版本或待保存按钮禁用。提交 dark 后、完成前编辑 light，set 先标 dirty=true；旧提交成功又清成 false，草稿仍 light、磁盘 dark、界面提示已保存且保存按钮没有 handler。从实际 save 闭包执行、延迟 invoke promise 后验证该状态成立。多次保存以及保存期间放弃同样没有统一状态管理；不依赖假设 IPC 请求必乱序，单次保存+编辑已足够证明。

普通单次保存失败仅设置错误提示，原 dirty 和草稿保留，后端内存不发布，这一支正确；它不消除上述成功竞态。放弃的 get_config 异常也未捕获；读取失败时 msg 被加载视图遮挡。

**建议：** 采用单飞保存；禁用相关操作或记录提交草稿版本，只在当前草稿与已提交版本一致时清 dirty，否则继续显示未保存。放弃读取有错误处理，失败保留草稿；明确加载失败显示。定点覆盖保存中编辑、重复保存、失败后重试和放弃即可。

### N4／MAJOR：local_models 同步阻塞 Tauri 主线程，慢/不可达 Ollama 时 UI 卡顿

**证据：** src-tauri/src/lib.rs:107–116；crates/dongyi-llm/src/lib.rs:130–134；App.tsx:1175–1183。

local_models 是普通 #[tauri::command] fn，直接执行 reqwest::blocking。前端 invoke 返回 Promise 不会把后端同步命令搬到后台。本机 tauri-macros-2.7.2/src/command/wrapper.rs:50 默认 Blocking，:242–246 分派，:424–428 在当前 handler 内直接调用函数，没有 spawn_blocking；[Tauri 官方命令文档](https://v2.tauri.app/develop/calling-rust/#async-commands) 也说明普通同步命令默认在主线程执行。故 brief 中“tauri sync command 线程不会阻塞 UI”的假设不成立。

打开设置或重进模型组会发查询。服务端接收后迟迟不响应时可等到 5s 请求超时，期间主线程窗口/IPC 处理受阻；3s/5s 超时限定请求等待而非证明 UI 不阻塞。不将需求方正常服务快速返回实测解释为慢服务路径已通过。

**建议：** async command 先短锁复制 base_url，然后使用 tauri::async_runtime::spawn_blocking 执行阻塞查询并 await；或将 HTTP 改用异步客户端。不能仅将函数改 async 后继续直接 blocking 调用。无需启动产品即可用局部受控慢服务验证查询与线程隔离。

### N5／MINOR：最常见的模型查询失败退化没有提示

**证据：** LLM lib.rs:135–147；App.tsx:1177–1191。

后端传输/解析失败正常返回 []，前端 promise 成功、failed=false；虽然退化手输，但提示只在 failed=true 时显示。因此 brief 要求的“列表空/失败退化为手输+提示”仅完成手输。**建议：** 对空列表同样显示无模型/不可达的提示，或返回可区分的结果。

### N6／MINOR：剪贴板兜底进程 JSON 受控输入难以编辑

**证据：** App.tsx:1063–1068。

value 每次取 JSON.stringify(cfg)，onChange 解析失败即忽略。删除 [] 的闭括号或逐字输入数组时中间文本不合法，cfg 不变，受控框回弹，注释“允许暂时非法”与实现相反。粘贴完整合法 JSON 可用，不能说明正常逐字编辑可用。**建议：** 单独保留文本草稿，在 blur/保存时校验数组，失败给提示且不发布。

### N7／MINOR：主题初始读取与更新事件无顺序保护

**证据：** App.tsx:94–108、113–127。

初始 get_config 与监听并行；若旧读取结果迟到到达，可能覆盖已经处理的新主题事件。初始 auto 读取迟到于 auto 更新，还可增加第二个媒体监听，而 mql/onMediaChange 只记录最后一个，后续切 light/dark 无法完整移除旧监听。正常窗口长期运行路径可用，当前没有对此初始化边界的排序保证；此项为静态可推导反例，未做桌面复现。

**建议：** 统一主题 apply/媒体句柄替换入口，先移除旧监听；用配置版本或本地更新代次拒绝事件之后的旧初始读取。补一个受控 promise 顺序用例即可。

无新增 BLOCKER。N5–N7 为非阻断整改项；N1–N4 是本轮必修项。

## 5. 必修清单与 P5 关注点

**最终 FAIL。** 放行前必须完成 N1 全量配置对弹窗状态的同步、N2 旧设置快照覆盖保护、N3 保存状态机、N4 查询移出主线程。复审采用这些反例的定点证据，不要求重复需求方已确认的 Enter/置顶/语向正常路径实测；源码变化后运行必要构建检查。

P5 关注点：

- RAG、术语表、翻译记忆引入的新字段必须与未知字段整体保留和配置冲突处理兼容；继续使用 Python 数据格式及同一份数据文件。
- 保存事务与事件携带一致的生效快照/版本；kind 切换失败回滚、缺失/空串跟随全局、显式覆盖保持一致，禁止破坏在途流不取消语义。
- 保持请求身份、检索代次、关闭/停止作废和解释惰性顺序；新上下文不要让旧结果写入新会话。
- 后台索引和文件解析使用后台任务，避免重复本轮同步命令阻塞主线程的问题。
- 保留输入原文、last_target retry、跨会话置顶、不抢焦点；发布时重编 exe，源码/构建/运行实例证据分别记录。
- 混合 DPI、PDF/终端和富格式剪贴板仍按既有证据边界补充；静默划词浮标的弃审限制不重新列为阻断。修正执行文档 §11 中过时的“P4 未开工”记录应由实施方完成，本轮未改该文档。
