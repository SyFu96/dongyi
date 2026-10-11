## 下载与运行

Windows x64 用户下载 `dongyi-v0.1.0-windows-x64.zip`，**完整解压**后双击 `dongyi.exe`（无需安装 Python）。

- 本地翻译需自行安装 [Ollama](https://ollama.com/) 并下载模型；云端翻译需在「设置…」里配置自己的 OpenAI 兼容 API。
- 配置与日志保存在 `%APPDATA%\dongyi\`。
- 本版本为**首次公开测试版（Alpha）**。

## 主要功能

- 划词浮标 → 弹窗「译文 / 解释 / 追问 / 输入翻译」四个标签
- 本地 Ollama 与任意 OpenAI 兼容云端，支持按标签混合；可一键「严格离线」
- 解释/追问可联网检索；图形化设置窗口

## 许可与对应源码

懂译采用 **GPL-3.0-only**；第三方组件遵循各自许可，完整许可与版权声明见包内
`LICENSE`、`LICENSES/` 与 `THIRD_PARTY_NOTICES.md`。

- 本次二进制对应 tag：`v0.1.0`，commit：`<COMMIT>`
- 项目源码：<https://github.com/SyFu96/dongyi/archive/refs/tags/v0.1.0.zip>（另附 `dongyi-v0.1.0-source.zip`）
- 依赖对应源码、版本、修改情况：`release/SOURCE_CODE.md`
- 重建与替换 LGPL 组件：`release/BUILDING.md`

对应源码按 GPLv3 第 6(d) 条免费提供网络下载；若链接失效，请提交 Issue，发布者负责恢复可获取性。

## 校验

下载 `SHA256SUMS.txt` 核对附件。

> Ollama 与模型权重不随包分发；管理员权限窗口取词、剪贴板富格式还原存在已知限制。
