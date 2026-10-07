# -*- coding: utf-8 -*-
"""划译场景基准：三个本地模型的翻译速度对比（流式，测 TTFT 与 tokens/s）"""
import json, time, urllib.request

URL = "http://localhost:11434/api/chat"
TEXT = ("The transformer architecture replaced recurrent networks by processing "
        "all tokens in parallel, at the cost of quadratic attention complexity.")
MODELS = ["qwen3-vl:30b-a3b-instruct", "qwen3-vl-8b:latest", "gpt-oss:20b"]

def run(model, warm=False):
    body = {
        "model": model,
        "stream": True,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": "你是划词翻译引擎。把用户内容译成中文，只输出译文。"},
            {"role": "user", "content": TEXT},
        ],
    }
    if not warm:
        body["think"] = False  # 划译不要思考过程
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    ttft, ntok, out_len, first_out = None, 0, 0, ""
    with urllib.request.urlopen(req, timeout=600) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            msg = d.get("message", {})
            content = msg.get("content") or ""
            if content:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                ntok += 1
                out_len += len(content)
                if len(first_out) < 120:
                    first_out += content
    total = time.perf_counter() - t0
    return ttft, total, ntok, out_len, first_out

for m in MODELS:
    tag = m.split(":")[0]
    print(f"\n===== {m} =====", flush=True)
    try:
        t0 = time.perf_counter()
        run(m)  # 冷启动：加载模型 + 一次完整翻译
        cold = time.perf_counter() - t0
        print(f"  冷启动(含模型加载): {cold:6.1f}s", flush=True)
        ttft, total, ntok, out_len, first_out = run(m, warm=True)  # 热请求
        tps = ntok / total if total > 0 else 0
        print(f"  热请求: 首 token {ttft*1000:6.0f}ms | 总耗时 {total:5.1f}s | "
              f"约 {tps:4.1f} tok/s | 输出 {out_len} 字", flush=True)
        print(f"  译文开头: {first_out[:80]}", flush=True)
    except Exception as e:
        print(f"  失败: {e}", flush=True)
