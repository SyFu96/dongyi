# -*- coding: utf-8 -*-
"""领域（学科）适配：术语表加载与匹配、领域配置解析。

一个"领域"= config.domains 里的一条配置：
    {"name": 显示名, "note": 追加到 system prompt 的领域说明,
     "enabled": 是否出现在切换列表, "glossary_file": 术语表 CSV 路径,
     "kb_dirs": 知识库目录列表, "kb_enabled": 是否检索注入,
     "kb_for_translate": 翻译标签是否也检索}

术语表 CSV：每行 `原文,译文[,备注]`，UTF-8（带不带 BOM 都行），# 开头为注释。
文件在请求时按 mtime 热加载，改表无需重启。
"""

from __future__ import annotations

import csv
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# 注入 prompt 的术语条数上限（防止术语表过大撑爆上下文）
MAX_TERMS_INJECTED = 60
# 领域说明追加到 prompt 的长度上限
MAX_NOTE_CHARS = 2000
# 术语表最大条数（超过部分忽略，防误配大文件）
MAX_GLOSSARY_ENTRIES = 20000
# 领域 id 允许的字符（id 会拼进文件路径，必须收紧）
DOMAIN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

GLOSSARY_HEADER = "术语对照（以下译法必须严格遵守，不得改写或另创译名）："

_cache_lock = threading.Lock()
_glossary_cache: dict[str, tuple[tuple[float, int], list[tuple[str, str, str]]]] = {}


def valid_id(domain_id: str) -> bool:
    return bool(DOMAIN_ID_RE.match(domain_id or ""))


def enabled_domains(cfg: dict) -> list[tuple[str, dict]]:
    """[(id, 配置)]，只保留 id 合法且 enabled 的领域，按 id 排序保证菜单稳定。"""
    out = []
    for did, dom in (cfg.get("domains") or {}).items():
        if valid_id(did) and isinstance(dom, dict) and dom.get("enabled", True):
            out.append((did, dom))
    return sorted(out, key=lambda pair: pair[0])


def resolve_active(cfg: dict) -> str:
    """当前激活领域 id；无效（不存在/未启用）时回退通用（空串）。"""
    active = cfg.get("active_domain") or ""
    if active and any(did == active for did, _ in enabled_domains(cfg)):
        return active
    return ""


def active_domain(cfg: dict) -> dict | None:
    did = resolve_active(cfg)
    if not did:
        return None
    return (cfg.get("domains") or {}).get(did)


def resolve_path(base_dir: Path, value: str) -> Path:
    """glossary_file 等相对路径基于数据目录解析；绝对路径原样使用。"""
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p)


def default_glossary_path(base_dir: Path, domain_id: str) -> Path:
    return base_dir / "glossaries" / f"{domain_id}.csv"


def load_glossary(path: Path) -> list[tuple[str, str, str]]:
    """读取术语表 → [(原文, 译文, 备注)]；文件不存在/损坏返回空表（不抛出）。

    按文件的 (mtime, size) 缓存，内容变了自动重读。
    """
    try:
        stat = path.stat()
        key = str(path)
        stamp = (stat.st_mtime, stat.st_size)
    except OSError:
        return []
    with _cache_lock:
        cached = _glossary_cache.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
    entries: list[tuple[str, str, str]] = []
    seen: dict[str, tuple[str, str, str]] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                first = (row[0] or "").strip()
                if not first or first.startswith("#"):
                    continue
                if len(row) < 2:
                    continue
                translation = (row[1] or "").strip()
                if not translation:
                    continue
                note = (row[2] or "").strip() if len(row) > 2 else ""
                # 同一原文多次出现时，后面的行生效（便于在表尾覆盖修正）
                seen[first.lower()] = (first, translation, note)
                if len(seen) >= MAX_GLOSSARY_ENTRIES:
                    log.warning("术语表 %s 超过 %s 条，多余条目被忽略", path, MAX_GLOSSARY_ENTRIES)
                    break
        entries = list(seen.values())
    except (OSError, csv.Error, UnicodeError):
        log.warning("读取术语表失败：%s", path, exc_info=True)
        return []
    with _cache_lock:
        _glossary_cache[key] = (stamp, entries)
    return entries


def match_terms(text: str, glossary: list[tuple[str, str, str]],
                limit: int = MAX_TERMS_INJECTED) -> list[tuple[str, str, str]]:
    """返回在 text 中命中的术语（大小写不敏感包含匹配），长术语排前面。"""
    if not text or not glossary:
        return []
    lowered = text.lower()
    hits = [entry for entry in glossary if entry[0].lower() in lowered]
    hits.sort(key=lambda entry: len(entry[0]), reverse=True)
    return hits[:limit]


def format_glossary(matches: list[tuple[str, str, str]]) -> str:
    if not matches:
        return ""
    lines = [GLOSSARY_HEADER]
    for term, translation, note in matches:
        if note:
            lines.append(f"- {term} → {translation}（{note}）")
        else:
            lines.append(f"- {term} → {translation}")
    return "\n".join(lines)


def matched_glossary_text(base_dir: Path, domain_id: str, dom: dict, text: str) -> str:
    """该领域下，把划词文本命中的术语拼成可注入 system prompt 的文本。

    glossary_file 未配置时按默认路径 glossaries/<id>.csv 兜底。
    """
    value = (dom.get("glossary_file") or "").strip()
    path = resolve_path(base_dir, value) if value else default_glossary_path(base_dir, domain_id)
    return format_glossary(match_terms(text, load_glossary(path)))


def domain_note_text(dom: dict) -> str:
    note = (dom.get("note") or "").strip()
    return note[:MAX_NOTE_CHARS]
