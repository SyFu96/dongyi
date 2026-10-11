# -*- coding: utf-8 -*-
"""翻译记忆（TM）：用户确认过的句对，翻译时作为相似句参考注入。

存储：tm/<领域id>.jsonl，每行 {"src": 原文, "tgt": 译文, "time": 时间戳}。
通用模式（未选领域）也有自己的 tm/general.jsonl，按领域隔离互不污染。
检索：字符 bigram / 英文词 Jaccard 相似度，超阈值的前 N 条作为参考译例。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from knowledge import tokenize

log = logging.getLogger(__name__)

# 参考译例条数与相似度阈值
MAX_EXAMPLES = 3
MIN_SIMILARITY = 0.35
# 注入 prompt 的预算（字符）
CONTEXT_BUDGET = 1200
# 检索扫描的最近条数上限（jsonl 追加写，新条目在尾部更有参考价值）
MAX_SCAN_ENTRIES = 3000
# 过长的句对不作为示例（整段翻译作为 few-shot 意义不大）
MAX_PAIR_CHARS = 600

EXAMPLE_HEADER = "以下是用户确认过的相似句对参考译例（保持术语与风格一致，不必逐字照搬）："


def similarity(a: str, b: str) -> float:
    """token 集合的 Jaccard 相似度；任一侧为空返回 0。"""
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class TmStore:
    """按领域读写翻译记忆；文件按 (mtime, size) 缓存，写入后立即可读。"""

    def __init__(self, tm_dir: Path) -> None:
        self._dir = tm_dir
        self._lock = threading.Lock()
        self._cache: dict[Path, tuple[tuple[float, int], list[dict]]] = {}

    def path_for(self, domain_id: str) -> Path:
        safe = domain_id if domain_id and domain_id.replace("-", "").replace("_", "").isalnum() \
            else "general"
        return self._dir / f"{safe}.jsonl"

    def _load(self, path: Path) -> list[dict]:
        try:
            stat = path.stat()
            stamp = (stat.st_mtime, stat.st_size)
        except OSError:
            return []
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == stamp:
                return cached[1]
        entries: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict) and obj.get("src") and obj.get("tgt"):
                        entries.append(obj)
        except OSError:
            log.warning("读取翻译记忆失败：%s", path, exc_info=True)
            return []
        with self._lock:
            self._cache[path] = (stamp, entries)
        return entries

    def append(self, domain_id: str, src: str, tgt: str) -> bool:
        src, tgt = (src or "").strip(), (tgt or "").strip()
        if not src or not tgt:
            return False
        path = self.path_for(domain_id)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"src": src, "tgt": tgt, "time": time.time()},
                                    ensure_ascii=False) + "\n")
        except OSError:
            log.warning("写入翻译记忆失败：%s", path, exc_info=True)
            return False
        with self._lock:
            self._cache.pop(path, None)  # 主动失效缓存
        return True

    def count(self, domain_id: str) -> int:
        return len(self._load(self.path_for(domain_id)))

    def clear(self, domain_id: str) -> int:
        path = self.path_for(domain_id)
        removed = len(self._load(path))
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("清空翻译记忆失败：%s", path, exc_info=True)
            return 0
        with self._lock:
            self._cache.pop(path, None)
        return removed

    def example_context(self, domain_id: str, text: str,
                        max_examples: int = MAX_EXAMPLES,
                        min_similarity: float = MIN_SIMILARITY,
                        budget: int = CONTEXT_BUDGET) -> str:
        """检索相似句对并拼成注入文本；无达标条目返回空串。"""
        text = (text or "").strip()
        if not text:
            return ""
        entries = self._load(self.path_for(domain_id))[-MAX_SCAN_ENTRIES:]
        candidates = [(e["src"], e["tgt"]) for e in entries
                      if len(e["src"]) <= MAX_PAIR_CHARS and len(e["tgt"]) <= MAX_PAIR_CHARS]
        if not candidates:
            return ""
        scored = sorted(
            ((similarity(text, src), src, tgt) for src, tgt in candidates),
            key=lambda item: item[0], reverse=True,
        )
        blocks: list[str] = []
        total = 0
        for score, src, tgt in scored:
            if score < min_similarity or len(blocks) >= max_examples:
                break
            block = f"原文：{src}\n译文：{tgt}"
            if total + len(block) > budget:
                break
            blocks.append(block)
            total += len(block)
        if not blocks:
            return ""
        return EXAMPLE_HEADER + "\n" + "\n".join(blocks)
