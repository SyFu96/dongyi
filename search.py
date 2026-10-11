# -*- coding: utf-8 -*-
"""联网检索客户端：Ollama 托管 web_search（https://ollama.com/api/web_search）。

启用条件：config.web_search.enabled 为真，且配置了 api_key（或环境变量 OLLAMA_API_KEY）。
本地模型与云端模型都能用它给"解释/追问"补充实时信息。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://ollama.com/api/web_search"
ENV_KEY = "OLLAMA_API_KEY"


class SearchError(Exception):
    pass


class SearchCancelled(Exception):
    """检索被取消（发送前检查或响应被关闭）。"""


def api_key(ws: dict | None) -> str:
    """优先取 config.web_search.api_key，其次环境变量 OLLAMA_API_KEY。"""
    return ((ws or {}).get("api_key") or os.environ.get(ENV_KEY) or "").strip()


def has_key(ws: dict | None) -> bool:
    return bool(api_key(ws))


def web_search(query: str, ws: dict | None = None, timeout: float = 12.0,
               cancelled=None, on_conn=None) -> list[dict]:
    """执行一次检索，返回 [{title,url,content}, ...]；失败抛 SearchError。

    - cancelled(): 返回 True 时在发送前放弃、并在收到响应后立即关闭，抛 SearchCancelled。
    - on_conn(resp): 收到响应对象时回调，供调用方持有以便取消时关闭。
    """
    key = api_key(ws)
    if not key:
        raise SearchError("未配置 Ollama API key（config.web_search.api_key 或 OLLAMA_API_KEY）")
    endpoint = (ws or {}).get("endpoint") or DEFAULT_ENDPOINT
    body = json.dumps({
        "query": query,
        "max_results": int((ws or {}).get("max_results", 5)),
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    if cancelled is not None and cancelled():
        raise SearchCancelled

    resp = None
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        if on_conn is not None:
            on_conn(resp)  # 暴露给调用方：取消时可 close() 中断读取
        if cancelled is not None and cancelled():
            raise SearchCancelled
        data = json.loads(resp.read().decode("utf-8", "replace"))
    except SearchCancelled:
        raise
    except urllib.error.HTTPError as e:
        raise SearchError(f"检索失败 HTTP {e.code}") from e
    except Exception as e:  # noqa: BLE001 — 网络/解析错误统一为 SearchError
        if cancelled is not None and cancelled():
            raise SearchCancelled from e
        raise SearchError(f"检索请求失败：{e}") from e
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
    results = data.get("results") or []
    return [r for r in results if isinstance(r, dict) and r.get("content")]


def format_results(results: list[dict], max_chars: int = 4000) -> str:
    """把检索结果拼成可注入 system prompt 的文本；无有效内容返回空串。"""
    blocks: list[str] = []
    total = 0
    for r in results:
        content = (r.get("content") or "").strip()
        if not content:
            continue
        block = f"【{r.get('title', '')}】{r.get('url', '')}\n{content}"
        if total + len(block) > max_chars:
            break
        blocks.append(block)
        total += len(block)
    if not blocks:
        return ""
    return ("以下是实时网络检索结果（可能过时或有误，请甄别后引用，保留链接）：\n\n"
            + "\n\n".join(blocks))
