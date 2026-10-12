# 对应源码（SOURCE_CODE）

本文件说明本二进制（`dongyi-v0.1.1-windows-x64.zip`）**对应版本**的源码获取位置。
按 **GPLv3 第 6(d) 条**，源码通过网络免费提供；若链接失效，请在本仓库提交 Issue，发布者负责恢复可获取性。

## 本项目

| 项 | 位置 |
|---|---|
| 懂译 v0.1.1（含构建脚本与依赖锁） | `https://github.com/SyFu96/dongyi/archive/refs/tags/v0.1.1.zip` |
| 同版本源码资产 | `dongyi-v0.1.1-source.zip`（Release 附件） |

## 依赖（实际分发组件）

| 组件 | 版本 | 许可 | 对应源码 |
|---|---|---|---|
| PySide6 / shiboken6 | 6.11.2 | LGPL-3.0（另有 GPL/商业选项） | `https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/`（`pyside-setup-everywhere-src-6.11.2.tar.xz`） |
| Qt | 6.11.2 | 见 `LICENSES/` 与 Qt 官方清单 | `https://download.qt.io/archive/qt/6.11/6.11.2/single/`（`qt-everywhere-src-6.11.2.tar.xz`） |
| pynput | 1.8.2 | LGPL-3.0 | `https://github.com/moses-palmer/pynput/archive/refs/tags/v1.8.2.tar.gz` |
| pywin32 | 312 | 混合（PSF 等） | `https://github.com/mhammond/pywin32`（tag `b312`） |
| uiautomation | 2.0.29 | Apache-2.0 | `https://github.com/yinkaisheng/Python-UIAutomation-for-Windows` |
| pypdf | 6.20.0 | BSD-3-Clause | `https://github.com/py-pdf/pypdf`（tag `v6.20.0`） |
| python-docx | 1.2.0 | MIT | `https://github.com/python-openxml/python-docx`（tag `v1.2.0`） |
| lxml | 6.1.3 | BSD-3-Clause（捆绑的 libxml2/libxslt 等见随包 LICENSES.txt） | `https://github.com/lxml/lxml`（tag `lxml-6.1.3`） |
| typing-extensions | 4.16.0 | PSF-2.0 | `https://github.com/python/typing_extensions`（tag `4.16.0`） |
| comtypes | 1.4.17 | MIT | `https://github.com/enthought/comtypes` |
| six | 1.17.0 | MIT | `https://github.com/benjaminp/six` |
| packaging | 26.3 | Apache-2.0 / BSD | `https://github.com/pypa/packaging` |
| setuptools | 84.0.0 | MIT（含内嵌组件） | `https://github.com/pypa/setuptools` |
| Python 运行时 | 3.14.6 | PSF | `https://www.python.org/downloads/release/python-3146/` |
| PyInstaller 运行时引导 | 6.22.3 | GPL 兼容特殊条款（bootloader） | `https://github.com/pyinstaller/pyinstaller`（tag `v6.22.3`） |
| OpenSSL（Qt 附带） | 见包内 | Apache-2.0 | `https://www.openssl.org/source/` |

> 精确的 sdist/commit 以 `uv.lock` 与上表为准。**PySide6 源码包不能代替 Qt 本体源码**；Qt 若走仓库下载方式需包含必要子模块。
> lxml 的 Windows wheel 捆绑 libxml2 / libxslt 等上游库，对应许可随 wheel 包内 `lxml/LICENSES/` 或上游项目分发。
> 若上游链接失效，发布者需将备份上传到同一 Release 并更新本文件。
