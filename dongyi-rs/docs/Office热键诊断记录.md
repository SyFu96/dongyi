# Office 中的 Alt 热键

2026-10-14：用户报告 Alt+Q/T 正常，Alt+E 无响应。

单独的 Alt 组合优先使用 `RegisterHotKey` 与 `WM_HOTKEY`，避免仅旁听按键后仍让前台软件执行菜单快捷键。其他组合保持原钩子处理；注册失败会写明原因并退回原路径。重复组合保持第一个绑定优先，长按不重复请求。

焦点在已有原文的懂译弹窗时，翻译/解释热键切换当前会话；设置窗和没有原文的输入窗仍不执行取词。此路径不重新读取弹窗中的文字。

定向检查：触发模块单测、应用类型检查、`check_alt_hotkeys` 本机系统消息检查通过，包括 Alt+E/Q/T、按键重复和重复配置。Office 自动检查未获得测试窗口的前台焦点，不能作为 Office 端验证通过的依据；实际效果以用户文档测试为准。

2026-10-14 用户后续确认：更新后，在 Word/PPT 中选中文字再按 Alt+E，可以打开懂译解释窗口。本轮实际验证完成。

诊断日志仍在 `%APPDATA%\dongyi\app.log`，只记录按键类型、前台进程和选区长度：

- `[hotkey] registered`：系统热键注册成功。
- `[hotkey] registration failed`：注册失败，后面是 Windows 错误。
- `[hotkey] received`：编排层已收到热键。
- `[hotkey] switch current popup`：在已有弹窗中切换标签。
- `[hotkey] skipped`：暂停状态、自家设置窗或空原文导致跳过。
- `[capture] ... selected_chars=0`：收到热键后未取到选中文字。
- `[capture] ... stale=true`：前台切换或会话变化使本次取词过期。
