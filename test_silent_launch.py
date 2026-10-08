"""验证真实快捷方式：无可见终端/启动页面、自启动入口有效、重复启动不增加实例。

uv run python test_silent_launch.py；验证后保留应用在后台运行。
"""

import json
import os
from pathlib import Path
import time

import win32gui
import win32process
from win32com.client import GetObject

import startup


def main():
    wmi = GetObject("winmgmts:")
    project = str(Path(__file__).resolve().parent).lower()

    def app_pids():
        processes = wmi.ExecQuery("SELECT ProcessId,CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")
        return {int(p.ProcessId) for p in processes if p.CommandLine and project in p.CommandLine.lower()
                and p.CommandLine.rstrip().lower().endswith('app.py"')}

    os.startfile(str(startup.startup_shortcut()))
    before = set()
    for _ in range(50):
        before = app_pids()
        if len(before) == 2:
            break
        time.sleep(0.1)
    assert len(before) == 2, before
    time.sleep(1)
    rows = []

    def collect(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] in before:
            rows.append({"class": win32gui.GetClassName(hwnd), "visible": bool(win32gui.IsWindowVisible(hwnd))})

    win32gui.EnumWindows(collect, None)
    assert not any(row["visible"] for row in rows), rows
    assert startup.is_enabled()
    os.startfile(str(startup.startup_shortcut()))
    time.sleep(2)
    after = set()
    for _ in range(30):
        after = app_pids()
        if after == before:
            break
        time.sleep(0.1)
    assert after == before, (before, after)
    print(json.dumps({"silent_launch": "PASS", "visible_app_or_console_windows": 0,
                      "autostart_enabled": True, "duplicate_launch": "PASS",
                      "pids": sorted(before), "native_windows": rows}))


if __name__ == "__main__":
    main()
