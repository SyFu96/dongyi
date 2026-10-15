# Chrome 网页取词修复（2026-10-15）

用户复现页面：https://www.zhihu.com/question/1953505443746944154/answer/1955350249339068569

## 证据与原因

在用户电脑运行只读 UIA 诊断，不发送按键、不读取剪贴板、不记录选中文字。
知乎正文焦点是 `QuestionAnswer-content` 容器，不支持 TextPattern；向上四层的 Document 支持 TextPattern，能够读到 59 字选区。旧逻辑仅检查焦点自身，因此失败后转入剪贴板兜底。

日志确认 Chrome 多次收到解释热键，取词为空，连按时出现大量过期结果。显式任务此前在出队后先调用 UIA，再检查有效性，会继续执行已过期任务。失败事件 `capture:fail` 没有前端监听，用户看起来毫无响应。

Alt+Q 的按键也收到；旧输入窗口首次显示时仍设为不可聚焦，且未取消在途取词。尚未证明这两个缺陷完整解释了用户报告的 Alt+Q 无窗口现象，因此新增原生窗口显示结果、可见状态和位置日志以便核查。

## 修改

- 沿同一进程的 UIA 父链寻找首个文本宿主，最多 16 层；遇到文档、顶层窗口或查找超过一秒即停止继续向上。已有 TextPattern 的焦点仍按原路径读取；不扫描整个页面、不跨窗口查找。
- 新取词淘汰旧任务；显式任务执行前检查有效性，消费结果时再次检查。输入热键仅取消取词，保留已打开会话的翻译和检索。
- Alt+Q 显示、恢复并激活输入窗。原生操作失败会记录日志。
- 显式取词失败显示可操作的中文提示，不触发空文本模型请求；静默拖选失败仍不弹窗。

剪贴板准入、备份与还原规则不变；未将 Chrome 加入自动剪贴板兜底白名单。

## 验证

- 捕获 crate 现有 SAFEARRAY 回归测试通过。
- 前端 TypeScript/Vite 构建通过；Rust 发布编译通过。
- 2026-10-15 09:34 安装更新，PID 8540；可执行文件哈希一致，配置文件哈希保持不变，Alt+E/Q/T 均注册成功。
- 向本程序的热键线程投递输入命令，原生窗口在首次唤起、已打开再唤起两种情况下均可见；后端显示操作均返回成功。这项检查未向 Chrome 或其他应用发送模拟按键，不能替代实体热键测试。
- UIA 父级能取得选区的证据来自上述电脑实测，不能用编译通过代替页面最终验收。
- 用户已确认最终安装后的知乎浮标、Alt+E/T/Q 恢复。

诊断例子：`cargo run -p dongyi-capture --example probe_chrome_selection --locked`，100 秒内只读取当前 Chrome 的控件类型、类名和选区长度。

参考：[Chromium UI Automation 文档](https://chromium.googlesource.com/chromium/src/+/main/docs/accessibility/browser/uiautomation.md)。

旧版备份：`%LOCALAPPDATA%\dongyi\backup-chrome-selection-20261015-093425`。
