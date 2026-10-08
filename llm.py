# -*- coding: utf-8 -*-
"""M3 Ollama /api/chat 流式客户端（NDJSON，非 SSE）。

架构：
- stream_chat：纯函数式核心（无 Qt），控制台测试可直接调用。
- LlmClient：QObject，translate/explain 各一条常驻工作线程；
  取消靠 worker 持有连接引用，主线程 close() 断流，worker 捕获异常静默退出。
- 新请求自动取消同 kind 旧请求（不取消会堆队列，"越用越卡"的头号原因）。
"""

from __future__ import annotations

import http.client
import json
import logging
import queue
import threading
import urllib.parse
from typing import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- 错误类型


class LlmError(Exception):
    pass


class OllamaConnectError(LlmError):
    pass


class OllamaModelError(LlmError):
    pass


class OllamaHttpError(LlmError):
    pass


class OllamaTimeoutError(LlmError):
    pass


class _StreamAborted(Exception):
    """内部取消信号：连接被 close() 断开、或 chunk 间检测到取消。"""


# ---------------------------------------------------------------- 核心 HTTP 细节


def _parse_base_url(base_url: str) -> tuple[str, int, str]:
    p = urllib.parse.urlparse(base_url.strip() or "http://localhost:11434")
    host = p.hostname or "localhost"
    port = p.port or 80
    path = (p.path.rstrip("/") or "") + "/api/chat"
    return host, port, path


def _read_error_body(resp: http.client.HTTPResponse) -> str:
    try:
        return resp.read().decode("utf-8", "replace")[:200]
    except Exception:  # noqa: BLE001
        return ""


def stream_chat(
    cfg: dict,
    kind: str,
    text: str,
    on_chunk: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    options: dict | None = None,
    on_conn: Callable[[http.client.HTTPConnection], None] | None = None,
) -> str:
    """发起一条流式请求并返回完整文本。

    - cancelled(): 返回 True 时尽快终止，抛 _StreamAborted。
    - on_conn(conn): 连接建立后立刻回调（供外部持有以便取消）。
    - 连接超时 3s；连上后单次读超时放宽到 60s（两 chunk 间隔上限即视为死流）。
    """
    host, port, path = _parse_base_url(cfg["base_url"])
    body = {
        "model": cfg["model"],
        "stream": True,
        "think": False,
        "keep_alive": cfg.get("keep_alive", "30m"),
        "messages": [
            {"role": "system", "content": cfg["prompts"][kind]},
            {"role": "user", "content": text},
        ],
    }
    if options:
        body["options"] = options
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    conn = http.client.HTTPConnection(host, port, timeout=3)
    if on_conn is not None:
        on_conn(conn)
    try:
        conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        # TCP 连接用 3s 超时；请求已发出后，读响应放宽到 60s：
        # 首字节要等模型加载（冷启动可达 30s），不能被连接超时误杀
        if conn.sock is not None:
            conn.sock.settimeout(60.0)
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException) as e:
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise OllamaConnectError(
            f"无法连接 Ollama（{cfg['base_url']}），请确认 `ollama serve` 已启动"
        ) from e

    try:
        if resp.status == 404:
            log.debug("404 body: %s", _read_error_body(resp))
            raise OllamaModelError(f"模型不存在（{cfg['model']}），请执行 ollama pull {cfg['model']}")
        if resp.status != 200:
            raise OllamaHttpError(f"Ollama 返回 HTTP {resp.status}: {_read_error_body(resp)}")

        parts: list[str] = []
        while True:
            if cancelled is not None and cancelled():
                raise _StreamAborted
            line = resp.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                log.debug("忽略无法解析的行: %r", line[:120])
                continue
            if obj.get("error"):
                raise OllamaHttpError(str(obj["error"]))
            delta = (obj.get("message") or {}).get("content") or ""
            if delta:
                parts.append(delta)
                if on_chunk is not None:
                    on_chunk(delta)
            if obj.get("done"):
                break
    except _StreamAborted:
        raise
    except TimeoutError as e:  # socket.timeout 在 Py3.10+ 即 TimeoutError
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise OllamaTimeoutError("响应超时（60s 无输出），请重试") from e
    except (OSError, http.client.HTTPException) as e:
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise OllamaHttpError(f"流式传输中断：{type(e).__name__}: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return "".join(parts)


# ---------------------------------------------------------------- 工作线程

_SHUTDOWN = object()
_PREHEAT_ID = 0  # 预热/保活请求占用 id=0；真实请求 id 从 1 开始


class _Worker(threading.Thread):
    """单 kind 请求工作线程：串行执行；同一时刻最多一个活跃请求。"""

    def __init__(self, client: "LlmClient", kind: str) -> None:
        super().__init__(name=f"llm-{kind}", daemon=True)
        self._client = client
        self._kind = kind
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._inflight: http.client.HTTPConnection | None = None

    def submit(self, item: tuple[int, str | None]) -> None:
        self._q.put(item)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            conn = self._inflight
        if conn is not None:
            try:
                conn.close()  # worker 正阻塞在 readline；断流 → 捕获 → 静默退出
            except Exception:  # noqa: BLE001
                pass

    def _attach_conn(self, conn: http.client.HTTPConnection) -> None:
        with self._lock:
            self._inflight = conn
            if self._cancel_requested:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def _is_current(self, req_id: int) -> bool:
        if req_id == _PREHEAT_ID:
            return self._client._wants_warmup
        return req_id == self._client._current_id(self._kind)

    def _is_cancelled(self, req_id: int) -> bool:
        # 取消 = 手动取消标志，或被更新 id 的请求取代
        if self._cancel_requested:
            return True
        return not self._is_current(req_id)

    def run(self) -> None:
        while True:
            item = self._q.get()
            if item is _SHUTDOWN:
                break
            req_id, text = item
            try:
                if not self._is_current(req_id):
                    continue  # 排队期间已被取代/取消
                with self._lock:
                    self._cancel_requested = False

                if text is None:
                    self._run_warmup()
                else:
                    self._run_request(req_id, text)
            except Exception:  # noqa: BLE001 — run 本身永不抛出
                log.exception("LLM worker(%s) 任务异常", self._kind)

    def _run_warmup(self) -> None:
        try:
            stream_chat(
                self._client._cfg,
                self._kind,
                "-",
                options={"num_predict": 1},
                cancelled=lambda: self._cancel_requested,
                on_conn=self._attach_conn,
            )
            log.info("预热/保活完成（model=%s）", self._client._cfg["model"])
        except Exception as e:  # noqa: BLE001 — 预热失败只记日志，不打扰用户
            log.warning("预热/保活请求失败：%s", e)

    def _run_request(self, req_id: int, text: str) -> None:
        def cancelled() -> bool:
            return self._is_cancelled(req_id)

        def on_chunk(delta: str) -> None:
            self._client.chunk.emit(self._kind, delta)

        try:
            full = stream_chat(
                self._client._cfg,
                self._kind,
                text,
                on_chunk=on_chunk,
                cancelled=cancelled,
                on_conn=self._attach_conn,
            )
        except _StreamAborted:
            return
        except LlmError as e:
            if cancelled():
                return
            self._client.failed.emit(self._kind, str(e))
            return
        except Exception:  # noqa: BLE001
            log.exception("LLM 未知错误")
            if not cancelled():
                self._client.failed.emit(self._kind, "未知错误，请查看日志")
            return
        if not cancelled():
            self._client.finished.emit(self._kind, full)


class LlmClient(QObject):
    chunk = Signal(str, str)  # (kind, delta)
    finished = Signal(str, str)  # (kind, full_text)
    failed = Signal(str, str)  # (kind, error_msg)

    _wants_warmup = False  # 预热请求挂在当前 id 之外，由该开关控制有效性

    def __init__(self, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._id = {"translate": 1, "explain": 1}
        self._id_lock = threading.Lock()
        self._workers = {
            "translate": _Worker(self, "translate"),
            "explain": _Worker(self, "explain"),
        }
        for w in self._workers.values():
            w.start()

    def _current_id(self, kind: str) -> int:
        with self._id_lock:
            return self._id[kind]

    def request(self, kind: str, text: str) -> None:
        """新请求；自动取消同 kind 的旧请求（含断流）。"""
        self.cancel(kind)
        with self._id_lock:
            self._id[kind] += 1
            rid = self._id[kind]
        self._workers[kind].submit((rid, text))

    def cancel(self, *kinds: str) -> None:
        with self._id_lock:
            self._id.update({k: -1 for k in kinds})  # 排队中的全部失效
        for k in kinds:
            self._workers[k].cancel()

    def preheat(self) -> None:
        """启动预热与 25min 保活：一条 num_predict=1 的请求消化冷启动。"""
        self._wants_warmup = True
        # warmup 用 id=0 排队执行；真实请求（id>=1）到来时它自动让位
        self._workers["translate"].submit((_PREHEAT_ID, None))

    def close(self) -> None:
        for w in self._workers.values():
            w.cancel()
            w.submit(_SHUTDOWN)
