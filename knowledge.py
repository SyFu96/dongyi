# -*- coding: utf-8 -*-
"""个人知识库（RAG）：文档解析、分块、BM25 索引与检索。

用法（App 持有一个 KnowledgeStore）：
    store = knowledge.KnowledgeStore(DATA_DIR / "kb_index")
    store.refresh(dirs)                      # 后台线程增量重建（按 mtime+size）
    hits = store.search(query, dirs=[...])   # 本地毫秒级

支持的格式：txt / md / csv / json 直读，pdf 用 pypdf，docx 用 python-docx。
索引持久化在 kb_index/index.json；分块按段落聚合到约 500 字符，保留来源路径。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".pdf", ".docx"}
# 单文件大小上限（PDF 解析慢，避免误选巨型文件拖垮索引）
MAX_FILE_BYTES = 20 * 1024 * 1024
CHUNK_TARGET = 500   # 分块目标长度（字符）
CHUNK_HARD = 1500    # 单段硬上限
# 注入 system prompt 的片段预算（字符）
CONTEXT_BUDGET = 2000
CONTEXT_TOP_K = 3

KB_HEADER = "以下是用户知识库中检索到的相关片段（来自个人文档，供参考甄别，标注了来源）："

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文/数字按词，中文按字符 bigram（检索与相似度共用）。"""
    lowered = (text or "").lower()
    tokens = _WORD_RE.findall(lowered)
    # 找出连续中文段，逐段做 bigram；单字中文段保留单字
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _split_long(paragraph: str, hard: int) -> list[str]:
    if len(paragraph) <= hard:
        return [paragraph]
    pieces = []
    while paragraph:
        if len(paragraph) <= hard:
            pieces.append(paragraph)
            break
        cut = paragraph.rfind(" ", 0, hard)
        if cut < hard // 2:
            cut = hard
        pieces.append(paragraph[:cut])
        paragraph = paragraph[cut:].lstrip()
    return pieces


def chunk_text(text: str, target: int = CHUNK_TARGET, hard: int = CHUNK_HARD) -> list[str]:
    """按空行分段，聚合到约 target 字符；超长段再切。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        for piece in _split_long(para, hard):
            if buf and len(buf) + len(piece) + 1 > target:
                chunks.append(buf)
                buf = piece
            else:
                buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


# ---------------------------------------------------------------- 文档解析


def parse_file(path: Path) -> str:
    """提取纯文本；不支持的格式/解析失败抛异常（调用方跳过该文件）。"""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".docx":
        return _parse_docx(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader  # 延迟导入：未用到 PDF 时不拖慢启动

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — 单页损坏不影响其余页
            continue
    return "\n\n".join(pages)


def _parse_docx(path: Path) -> str:
    import docx  # python-docx

    document = docx.Document(str(path))
    return "\n\n".join(p.text for p in document.paragraphs)


# ---------------------------------------------------------------- 索引与检索


def _norm_dir(d: str) -> str:
    """目录归一化（小写、去尾部斜杠），用于按前缀过滤分块归属。"""
    return os.path.normcase(os.path.abspath(d)).rstrip("\\/") + os.sep


class KnowledgeStore:
    """全局索引：files 记录每个文件的 mtime/size/分块数，chunks 保存文本。

    多个领域可指向同一批目录；refresh 传全部目录的并集，search 按领域的
    kb_dirs 前缀过滤。线程安全：refresh 在后台线程跑，结束后一次性换锁内数据。
    分词统计（tf/df/avgdl）按代数惰性构建，避免每次检索重复分词。
    """

    VERSION = 1

    def __init__(self, index_dir: Path) -> None:
        self._dir = index_dir
        self._path = index_dir / "index.json"
        self._lock = threading.Lock()
        self._files: dict[str, dict] = {}
        self._chunks: list[dict] = []  # {"path": str, "text": str}
        self._index_gen = 0            # chunks 变化时 +1
        self._built_gen = -1           # 统计缓存对应的代数
        self._counts: list[dict[str, int]] = []
        self._df: dict[str, int] = {}
        self._avgdl = 1.0
        self._load()

    # —— 持久化

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data.get("version") == self.VERSION:
                self._files = data.get("files") or {}
                self._chunks = data.get("chunks") or []
                self._index_gen += 1
        except Exception:  # noqa: BLE001 — 坏索引当空处理，重建即可
            log.debug("知识库索引读取失败（将重建）", exc_info=True)

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(
                {"version": self.VERSION, "files": self._files, "chunks": self._chunks},
                ensure_ascii=False,
            ), encoding="utf-8")
        except Exception:  # noqa: BLE001 — 保存失败不影响本次内存索引
            log.warning("知识库索引写入失败", exc_info=True)

    # —— 重建

    def refresh(self, dirs: list[str]) -> dict:
        """增量重建并返回统计 {"files": n, "chunks": n, "parsed": n, "errors": n}。"""
        wanted: dict[str, tuple[float, int]] = {}
        for d in dirs:
            root = Path(d)
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size > MAX_FILE_BYTES:
                    continue
                wanted[str(path.resolve())] = (stat.st_mtime, stat.st_size)

        with self._lock:
            old_by_path: dict[str, list[dict]] = {}
            for chunk in self._chunks:
                old_by_path.setdefault(chunk["path"], []).append(chunk)

        parsed = errors = 0
        new_chunks: list[dict] = []
        indexed: dict[str, dict] = {}
        for path_str, (mtime, size) in wanted.items():
            old = self._files.get(path_str)
            kept = None
            if old and old.get("mtime") == mtime and old.get("size") == size:
                kept = old_by_path.get(path_str)
            if kept is not None:
                new_chunks.extend(kept)
                indexed[path_str] = {"mtime": mtime, "size": size, "chunks": len(kept)}
                continue
            try:
                pieces = chunk_text(parse_file(Path(path_str)))
            except Exception as e:  # noqa: BLE001 — 单文件失败跳过（下次刷新重试）
                log.warning("知识库解析失败 %s：%s", path_str, e)
                errors += 1
                continue
            parsed += 1
            new_chunks.extend({"path": path_str, "text": piece} for piece in pieces)
            indexed[path_str] = {"mtime": mtime, "size": size, "chunks": len(pieces)}

        with self._lock:
            self._files = indexed
            self._chunks = new_chunks
            self._index_gen += 1
            stats = {"files": len(indexed), "chunks": len(new_chunks),
                     "parsed": parsed, "errors": errors}
        self._save()
        return stats

    # —— 检索

    def _ensure_stats(self) -> tuple[list[dict[str, int]], dict[str, int], float]:
        """返回 (每块词频, 词→块数, 平均块长)；chunks 未变时直接用缓存。"""
        with self._lock:
            if self._built_gen == self._index_gen:
                return self._counts, self._df, self._avgdl
            chunks = [dict(c) for c in self._chunks]
            gen = self._index_gen
        counts: list[dict[str, int]] = []
        df: dict[str, int] = {}
        total = 0
        for chunk in chunks:
            tf: dict[str, int] = {}
            for token in tokenize(chunk["text"]):
                tf[token] = tf.get(token, 0) + 1
            counts.append(tf)
            total += len(tf)
            for term in tf:
                df[term] = df.get(term, 0) + 1
        avgdl = total / len(chunks) if chunks else 1.0
        with self._lock:
            if self._index_gen == gen:  # 构建期间未被并发 refresh 覆盖
                self._counts, self._df, self._avgdl, self._built_gen = counts, df, avgdl, gen
        return counts, df, avgdl

    def search(self, query: str, dirs: list[str] | None = None,
               top_k: int = CONTEXT_TOP_K, min_score: float = 0.2) -> list[dict]:
        """BM25 检索 → [{"path","text","score"}]；dirs 限定检索的目录范围。

        min_score=0.2：只滤掉超常见词（大语料里 idf→0），小语料的精确命中仍可返回。
        """
        terms = set(tokenize(query))
        if not terms:
            return []
        with self._lock:
            if not self._chunks:
                return []
            chunks = [dict(c) for c in self._chunks]
        counts, df, avgdl = self._ensure_stats()
        n = len(chunks)
        allowed = None
        if dirs:
            prefixes = tuple(_norm_dir(d) for d in dirs if d)
            allowed = {i for i, c in enumerate(chunks)
                       if c["path"].lower().startswith(prefixes)}
            if not allowed:
                return []

        scored: list[tuple[float, int]] = []
        for i, tf in enumerate(counts):
            if allowed is not None and i not in allowed:
                continue
            if not tf:
                continue
            score = 0.0
            dl = sum(tf.values())
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * f * (BM25_K1 + 1) / (
                    f + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl))
            if score >= min_score:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [{"path": chunks[i]["path"], "text": chunks[i]["text"], "score": round(s, 3)}
                for s, i in scored[:top_k]]

    def stats(self, dirs: list[str] | None = None) -> dict:
        with self._lock:
            chunks = [dict(c) for c in self._chunks]
            files = dict(self._files)
        if dirs:
            prefixes = tuple(_norm_dir(d) for d in dirs if d)
            chunks = [c for c in chunks if c["path"].lower().startswith(prefixes)]
            paths = {c["path"] for c in chunks}
            files = {p: v for p, v in files.items() if p in paths}
        return {"files": len(files), "chunks": len(chunks)}


def context_for(store: KnowledgeStore | None, dom: dict, kind: str,
                text: str) -> str:
    """按领域配置决定是否检索，拼成可注入 system prompt 的文本。

    - explain 默认检索；translate/input 由 kb_for_translate 控制（默认关）；
    - chat 不检索（追问围绕原文/译文/解释已有上下文）；
    - 检索失败静默返回空串，不阻塞翻译主流程。
    """
    if store is None or not dom.get("kb_enabled"):
        return ""
    if kind == "chat":
        return ""
    if kind in ("translate", "input") and not dom.get("kb_for_translate"):
        return ""
    dirs = [d for d in (dom.get("kb_dirs") or []) if d]
    if not dirs:
        return ""
    try:
        hits = store.search(text, dirs=dirs)
    except Exception:  # noqa: BLE001 — 检索异常不阻塞翻译
        log.warning("知识库检索失败", exc_info=True)
        return ""
    return format_context(hits)


def format_context(hits: list[dict], budget: int = CONTEXT_BUDGET) -> str:
    if not hits:
        return ""
    blocks: list[str] = []
    total = 0
    for hit in hits:
        body = (hit.get("text") or "").strip()
        if not body:
            continue
        block = f"【来源】{hit.get('path', '')}\n{body}"
        if total + len(block) > budget:
            break
        blocks.append(block)
        total += len(block)
    if not blocks:
        return ""
    return KB_HEADER + "\n\n" + "\n\n".join(blocks)
