# -*- coding: utf-8 -*-
"""LLM 客户端独立测试（控制台跑，无 GUI）。

用法：
    .venv\\Scripts\\python.exe test_llm.py

跑一条翻译 + 一条解释，打印首字延迟 / 总耗时。
保持简单：直接调用 stream_chat 核心（无 Qt 依赖）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import llm

APP_DIR = Path(__file__).resolve().parent


def load_cfg() -> dict:
    cfg = {
        "base_url": "http://localhost:11434",
        "model": "qwen3-vl:30b-a3b-instruct",
        "keep_alive": "30m",
        "prompts": {
            "translate": "你是划词翻译引擎。自动识别语言：非中文译为中文，中文译为英文。只输出译文，保留换行与格式，不要任何解释。",
            "explain": "解释用户划选的文本。中文回复。",
        },
    }
    path = APP_DIR / "config.json"
    try:
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 — config.json 缺失则用内建默认
        print("(未找到 config.json，使用内建默认配置)")
    return cfg


def run_one(cfg: dict, kind: str, text: str) -> None:
    print(f"\n=== {kind} ===")
    t0 = time.perf_counter()
    first = {"t": None, "chars": 0}
    parts: list[str] = []
    try:
        def on_chunk(delta: str) -> None:
            if first["t"] is None:
                first["t"] = time.perf_counter()
            parts.append(delta)
            if first["chars"] == 0:
                print("[流式] ", flush=True, end="")
            first["chars"] += 1
            print(delta, flush=True, end="")

        full = llm.stream_chat(cfg, kind, text, on_chunk=on_chunk)
        dt = time.perf_counter() - t0
        ft = (first["t"] - t0) if first["t"] is not None else float("nan")
        print(f"\n[统计] 流式 chunk 数={first['chars']} 首字延迟 {ft:.2f}s 总耗时 {dt:.2f}s")
        assert full == "".join(parts), "完整文本与流式累计不一致"
        print("[校验] 流式累计与完整返回一致")
    except llm.LlmError as e:
        print(f"\n[失败] {e}")
        sys.exit(1)


def main() -> None:
    cfg = load_cfg()
    print(f"base_url={cfg['base_url']} model={cfg['model']}")
    run_one(cfg, "translate", "The transformer architecture processes sequences in parallel rather than sequentially.")
    run_one(cfg, "explain", "transformer")
    print("\n全部通过")


if __name__ == "__main__":
    main()
