# 第三方组件许可（Third-Party Notices）

本项目（划译）以 **GPL-3.0-only** 发布。它依赖以下第三方组件，各组件遵循其自身许可。

- **只分发源码**时，这些许可可随各自的包一并获得，通常无需额外操作。
- **分发打包后的二进制（exe / 目录包）**时，需按下表履行相应义务，尤其是 LGPL 组件的许可文本与源码/替换要求。

| 组件 | 许可 | 分发二进制时的要点 |
|---|---|---|
| PySide6 / shiboken6 | LGPL-3.0（另有 GPL / 商业选项） | Qt for Python。需遵守 LGPLv3：提供许可文本、对应源码获取方式，并保证用户可用兼容的替换库运行 |
| Qt（含 Qt Virtual Keyboard、Qt PDF 等随包模块） | 逐模块；常用模块 LGPLv3，**Qt Virtual Keyboard 为 GPLv3** | 按实际打包模块核对许可与第三方声明；本项目 GPL-3.0-only 与之兼容 |
| pynput | LGPL-3.0 | 同上（LGPLv3 义务）；纯 Python 模块，采用源码重组路径 |
| pywin32 | PSF（上游含混合许可组件） | 按上游各组件的许可文件处理 |
| uiautomation | Apache-2.0 | 保留版权与许可声明 |
| comtypes | MIT | 保留版权与许可声明 |
| six | MIT | 保留版权与许可声明 |
| packaging | Apache-2.0 / BSD | 保留版权与许可声明 |
| setuptools（含内嵌组件） | MIT 及内嵌组件各自许可 | 保留实际内嵌组件的声明 |
| Python 运行时 | PSF | 保留 Python 许可及相关版权声明 |
| OpenSSL（Qt 附带） | Apache-2.0 | 保留版权与声明 |

## 说明

- 本地翻译使用用户自行安装的 **Ollama**；模型权重不随本项目分发。
- 联网检索使用 Ollama 托管的 `web_search`，需要用户自己的 API key。
- 完整依赖版本见 `uv.lock`。

## 分发二进制（exe / 目录包）时的额外清单

仅"目录里 DLL 可见"不足以满足 LGPL。打包分发时，请在同一发布位置一并提供：

- 本项目**对应版本的源码**（含 `huayi.spec` 构建脚本与依赖锁 `uv.lock`）；
- 所分发 **LGPL 组件**（Qt/PySide6、pynput）的**对应源码获取方式与重建说明**；
- 随包的**许可文本**：`LICENSE`（GPL-3.0）、本文件、LGPLv3 / GPLv3 全文，以及 PySide6/shiboken6、pynput、pywin32、uiautomation、comtypes、six 与实际打包组件（含 Python 运行时）各自的许可声明；
- 一个 `SHA256SUMS` 校验文件。

本仓库 `release/` 目录即为发布二进制准备的合规材料：`release/LICENSES/`（许可文本）、`release/SOURCE_CODE.md`（对应源码位置）、`release/BUILDING.md`（重建/替换）、`release/README.txt`（用户说明）。

> 采用开源 GPL/LGPL 路径即需履行上述义务；若已购买 Qt 商业许可，可按其条款处理。

LGPLv3 全文：<https://www.gnu.org/licenses/lgpl-3.0.txt>
