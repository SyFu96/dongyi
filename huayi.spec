# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

用法：
    uv sync
    uv run pyinstaller --noconfirm huayi.spec

产出 dist/huayi/（目录包，便于检查依赖、满足 LGPL 的可替换性；见 THIRD_PARTY_NOTICES.md）。
运行 dist/huayi/huayi.exe 即可；配置与日志写入 %APPDATA%\\huayi\\。
"""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for _pkg in ("uiautomation", "comtypes"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas + [("assets/huayi.ico", "assets"), ("glossaries", "glossaries")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="huayi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/huayi.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="huayi",
)
