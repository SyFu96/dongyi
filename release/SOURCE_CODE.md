# 对应源码（SOURCE_CODE）

本文件说明本二进制（`huayi-v0.1.0-windows-x64.zip`）**对应版本**的源码获取位置。
按 **GPLv3 第 6(d) 条**，源码通过网络免费提供；若链接失效，请在本仓库提交 Issue，发布者负责恢复可获取性。

## 本项目

| 项 | 位置 |
|---|---|
| 划译 v0.1.0（含构建脚本与依赖锁） | `https://github.com/SyFu96/huayi/archive/refs/tags/v0.1.0.zip` |
| 同版本源码资产 | `huayi-v0.1.0-source.zip`（Release 附件） |

## 依赖（实际分发组件）

| 组件 | 版本 | 许可 | 对应源码 |
|---|---|---|---|
| PySide6 / shiboken6 | 6.11.2 | LGPL-3.0（另有 GPL/商业选项） | `https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/`（`pyside-setup-everywhere-src-6.11.2.tar.xz`） |
| Qt | 6.11.2 | 见 `LICENSES/` 与 Qt 官方清单 | `https://download.qt.io/archive/qt/6.11/6.11.2/single/`（`qt-everywhere-src-6.11.2.tar.xz`） |
| pynput | 1.8.2 | LGPL-3.0 | `https://github.com/moses-palmer/pynput/archive/refs/tags/v1.8.2.tar.gz` |
| pywin32 | 312 | 混合（PSF 等） | `https://github.com/mhammond/pywin32`（tag `b312`） |
| uiautomation | 2.0.29 | Apache-2.0 | `https://github.com/yinkaisheng/Python-UIAutomation-for-Windows` |
| comtypes | 1.4.17 | MIT | `https://github.com/enthought/comtypes` |
| six | 1.17.0 | MIT | `https://github.com/benjaminp/six` |
| packaging | 26.3 | Apache-2.0 / BSD | `https://github.com/pypa/packaging` |
| setuptools | 84.0.0 | MIT（含内嵌组件） | `https://github.com/pypa/setuptools` |
| Python 运行时 | 3.14.6 | PSF | `https://www.python.org/downloads/release/python-3146/` |
| OpenSSL（Qt 附带） | 见包内 | Apache-2.0 | `https://www.openssl.org/source/` |

> 精确的 sdist/commit 以 `uv.lock` 与上表为准。**PySide6 源码包不能代替 Qt 本体源码**；Qt 若走仓库下载方式需包含必要子模块。
> 若上游链接失效，发布者需将备份上传到同一 Release 并更新本文件。
