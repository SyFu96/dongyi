# 构建与替换（BUILDING）

本文件说明如何从对应源码重建本程序，以及如何替换 LGPL 组件，用于满足 LGPLv3 的相关义务。

## 重建应用

需要 Windows x64 与 [uv](https://docs.astral.sh/uv/)。在项目源码根目录执行：

```powershell
# 固定 Python 版本与依赖（见 pyproject.toml / uv.lock）
uv sync --frozen

# 修改依赖（例如 .venv\Lib\site-packages\pynput 中的源码）后，
# 用 --no-sync 避免覆盖你的改动：
uv run --no-sync pyinstaller --clean --noconfirm dongyi.spec

# 运行重建结果
.\dist\dongyi\dongyi.exe
```

## 替换 LGPL 组件（Qt / PySide6 / shiboken6）

- 运行包为 **onedir**：Qt 相关动态库位于 `_internal\PySide6\`、`_internal\shiboken6\`。
- 允许用户用**兼容的修改版**替换这些库；程序未对它们做完整性锁定。
- 兼容要求：Windows x64、与 Python 3.14 ABI 匹配的 PySide6 6.11.x、Qt 6.11.x 接口。
- Qt / PySide6 的重建见官方指南：
  - Qt Windows 构建：<https://doc.qt.io/qt-6.11/windows-building.html>
  - Qt for Python 构建：<https://doc.qt.io/qtforpython-6.11/building_from_source/index.html>

## 替换 LGPL 组件（pynput）

`pynput` 是纯 Python 模块，被 PyInstaller 收进归档（`noarchive=False`），因此采用 **LGPLv3 第 4(d)(0) 条的重组路径**：
提供应用源码、依赖源码与可运行的重建步骤（见上「重建应用」），使你能用修改后的 pynput 重新构建并运行。

具体：把修改后的 `pynput` 放到 `.venv\Lib\site-packages\pynput`（或按文档安装兼容的修改版），再执行上面的 `pyinstaller` 重建命令。

## 许可材料

- 项目许可：`LICENSE`（GPL-3.0）。
- 第三方许可与声明：`LICENSES/` 与 `THIRD_PARTY_NOTICES.md`。
- 对应源码位置：`SOURCE_CODE.md`。
