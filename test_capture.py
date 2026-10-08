# -*- coding: utf-8 -*-
"""取词链独立测试（控制台跑，覆盖各应用差异）。

用法：
    .venv\\Scripts\\python.exe test_capture.py

每轮先给 3 秒提示，去别的窗口选中文字；默认走 silent（纯 UIA）模式。
输入 e 回车可加测 explicit（含剪贴板兜底，会短暂占用并还原剪贴板）。
Ctrl+C 或输入 q 退出。
"""

from __future__ import annotations

import sys
import time

import capture


def read_one_line() -> str:
    try:
        return input("模式（回车=silent，e=explicit，q=退出）: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"


def main() -> None:
    print("=== 取词链测试 ===")
    print("提示：Chrome/Edge 首次 UIA 查询可能几百 ms（无障碍树激活），属正常。")
    while True:
        mode = read_one_line()
        if mode == "q":
            break
        if mode not in ("", "e"):
            print("未知模式，回车=silent / e=explicit / q=退出")
            continue

        for i in (3, 2, 1):
            print(f"3 秒内去别的窗口选中文字…… {i}")
            time.sleep(1)

        m = "explicit" if mode == "e" else "silent"
        t0 = time.perf_counter()
        sel = capture.get_selection(m)
        dt = (time.perf_counter() - t0) * 1000

        if sel is None:
            print(f"[{m}] 未取到（耗时 {dt:.0f} ms）")
        else:
            print(f"[{m}] source={sel.source} rect={sel.rect} truncated={sel.truncated} 耗时 {dt:.0f} ms")
            preview = sel.text.replace("\r", "").replace("\n", "\\n")
            if len(preview) > 120:
                preview = preview[:120] + "…"
            print(f"      text={preview}")
        print("-" * 60)

    print("测试结束")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出")
        sys.exit(0)
