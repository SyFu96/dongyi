# -*- coding: utf-8 -*-
"""M3 流式 LLM 客户端，双后端。

- provider="ollama"（默认）：本地 Ollama 原生 /api/chat（NDJSON）。
- provider="openai"：任意 OpenAI 兼容云端 /chat/completions（SSE），
  用 config.cloud.{base_url,model,api_key} 配置。

架构：
- stream_chat：纯函数式核心（无 Qt），按 provider 分发，控制台测试可直接调用。
- LlmClient：QObject，translate/explain/chat 各一条常驻工作线程；
  取消靠 worker 持有连接引用，主线程 close() 断流，worker 捕获异常静默退出。
- 新请求自动取消同 kind 旧请求（不取消会堆队列，"越用越卡"的头号原因）。
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
import queue
import socket
import threading
import urllib.parse
from typing import Callable

from PySide6.QtCore import QObject, Signal, Qt

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


class CloudError(LlmError):
    """云端 OpenAI 兼容后端：连接/HTTP/超时等运行时错误。"""


class CloudConfigError(CloudError):
    """云端配置缺失（base_url / model）。"""


class CloudAuthError(CloudError):
    """云端鉴权失败（401/403），通常是 api_key 无效。"""


class _StreamAborted(Exception):
    """内部取消信号：连接被 close() 断开、或 chunk 间检测到取消。"""


# ---------------------------------------------------------------- 核心 HTTP 细节


def _parse_base_url(base_url: str) -> tuple[str, int, str]:
    p = urllib.parse.urlparse(base_url.strip() or "http://localhost:11434")
    host = p.hostname or "localhost"
    port = p.port or 80
    path = (p.path.rstrip("/") or "") + "/api/chat"
    return host, port, path


def _parse_openai_url(base_url: str) -> tuple[str, int, str, bool]:
    """OpenAI 兼容地址 → (host, port, path, secure)。base_url 可含 /v1。"""
    p = urllib.parse.urlparse(base_url.strip())
    if not p.hostname:
        raise CloudConfigError(f"云端 base_url 无效：{base_url!r}")
    secure = p.scheme == "https"
    port = p.port or (443 if secure else 80)
    path = (p.path.rstrip("/") or "") + "/chat/completions"
    return p.hostname, port, path, secure


def _read_error_body(resp: http.client.HTTPResponse) -> str:
    try:
        return resp.read().decode("utf-8", "replace")[:200]
    except Exception:  # noqa: BLE001
        return ""


def is_loopback(host: str) -> bool:
    """严格判断回环地址：仅 localhost 或合法回环 IP（避免误放行 127.example.com）。"""
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def provider_for(cfg: dict, kind: str) -> str:
    """解析某个 kind 实际使用的后端。

    - cfg["offline"] 为真时强制本地（ollama），忽略云端路由。
    - 否则 cfg["kind_providers"] 可按标签覆盖，未覆盖回退全局 cfg["provider"]。
    """
    if cfg.get("offline"):
        return "ollama"
    return (cfg.get("kind_providers") or {}).get(kind) or cfg.get("provider", "ollama")


def stream_chat(
    cfg: dict,
    kind: str,
    text: str,
    on_chunk: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    options: dict | None = None,
    on_conn: Callable[[http.client.HTTPConnection], None] | None = None,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """发起一条流式请求并返回完整文本，按该 kind 解析出的 provider 分发。"""
    if provider_for(cfg, kind) == "openai":
        return _stream_openai(cfg, kind, text, on_chunk, cancelled, options, on_conn, messages)
    return _stream_ollama(cfg, kind, text, on_chunk, cancelled, options, on_conn, messages)


def _stream_ollama(
    cfg: dict,
    kind: str,
    text: str,
    on_chunk: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    options: dict | None = None,
    on_conn: Callable[[http.client.HTTPConnection], None] | None = None,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """本地 Ollama 原生 /api/chat（NDJSON）。

    - cancelled(): 返回 True 时尽快终止，抛 _StreamAborted。
    - on_conn(conn): 连接建立后立刻回调（供外部持有以便取消）。
    - 连接超时 3s；连上后单次读超时放宽到 60s（两 chunk 间隔上限即视为死流）。
    """
    host, port, path = _parse_base_url(cfg["base_url"])
    if cfg.get("offline") and not is_loopback(host):
        raise OllamaConnectError("已开启离线模式（offline=true），仅允许连接本机 Ollama")
    body = {
        "model": cfg["model"],
        "stream": True,
        "think": False,
        "keep_alive": cfg.get("keep_alive", "30m"),
        "messages": messages if messages is not None else [
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
    if cancelled is not None and cancelled():
        conn.close()
        raise _StreamAborted
    try:
        conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        # 用户可能在建立连接期间点击停止；此时取消线程还看不到 socket。
        if cancelled is not None and cancelled():
            conn.close()
            raise _StreamAborted
        # TCP 连接用 3s 超时；请求已发出后，读响应放宽到 60s：
        # 首字节要等模型加载（冷启动可达 30s），不能被连接超时误杀
        if conn.sock is not None:
            conn.sock.settimeout(60.0)
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException) as e:
        conn.close()
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
        finished = False
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
                finished = True
                break
        if not finished:
            raise OllamaHttpError("流式响应提前结束（未收到完成标记），请重试")
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


def _stream_openai(
    cfg: dict,
    kind: str,
    text: str,
    on_chunk: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    options: dict | None = None,
    on_conn: Callable[[http.client.HTTPConnection], None] | None = None,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """任意 OpenAI 兼容云端 /chat/completions（SSE）。"""
    if cfg.get("offline"):
        raise CloudConfigError("已开启离线模式（offline=true），禁止云端请求")
    cloud = cfg.get("cloud") or {}
    model = (cloud.get("model") or "").strip()
    base_url = (cloud.get("base_url") or "").strip()
    if not base_url or not model:
        raise CloudConfigError("云端未配置：请在 config.json 的 cloud 中填写 base_url 与 model")
    host, port, path, secure = _parse_openai_url(base_url)

    body = {
        "model": model,
        "stream": True,
        "messages": messages if messages is not None else [
            {"role": "system", "content": cfg["prompts"][kind]},
            {"role": "user", "content": text},
        ],
    }
    if options and options.get("num_predict"):
        body["max_tokens"] = options["num_predict"]  # OpenAI 兼容端点用 max_tokens
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = (cloud.get("api_key") or "").strip()
    if not api_key:
        # 支持环境变量注入：cloud.api_key_env 指定变量名，默认 OPENAI_API_KEY。
        env_name = (cloud.get("api_key_env") or "OPENAI_API_KEY").strip()
        api_key = (os.environ.get(env_name) or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    conn_cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
    conn = conn_cls(host, port, timeout=10)  # 公网 TLS/DNS 比本机慢，连接给 10s
    if on_conn is not None:
        on_conn(conn)
    if cancelled is not None and cancelled():
        conn.close()
        raise _StreamAborted
    try:
        conn.request("POST", path, body=data, headers=headers)
        if cancelled is not None and cancelled():
            conn.close()
            raise _StreamAborted
        if conn.sock is not None:
            conn.sock.settimeout(60.0)  # 连上后读超时放宽：等首 token / 长回答
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException) as e:
        conn.close()
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise CloudError(f"无法连接云端模型（{base_url}）：{e}") from e

    try:
        if resp.status in (401, 403):
            raise CloudAuthError(f"云端鉴权失败（HTTP {resp.status}）：请检查 cloud.api_key")
        if resp.status == 404:
            log.debug("404 body: %s", _read_error_body(resp))
            raise CloudError(f"云端模型不存在（{model}）：请检查 cloud.base_url 与 cloud.model")
        if resp.status != 200:
            raise CloudError(f"云端返回 HTTP {resp.status}: {_read_error_body(resp)}")

        parts: list[str] = []
        finished = False
        while True:
            if cancelled is not None and cancelled():
                raise _StreamAborted
            line = resp.readline()
            if not line:
                break
            line = line.strip()
            # SSE：只处理 "data:" 行，忽略空行与注释。
            if not line.startswith(b"data:"):
                continue
            payload = line[len(b"data:"):].strip()
            if payload == b"[DONE]":
                finished = True
                break
            try:
                obj = json.loads(payload.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                log.debug("忽略无法解析的 SSE 行: %r", payload[:120])
                continue
            if obj.get("error"):
                raise CloudError(str(obj["error"]))
            choices = obj.get("choices") or []
            if choices:
                if choices[0].get("finish_reason"):
                    finished = True  # 部分服务端不发 [DONE]，以结束原因判定
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    parts.append(delta)
                    if on_chunk is not None:
                        on_chunk(delta)
        if not finished:
            if parts:
                log.warning("云端流未收到结束标记，返回已收到内容")
            else:
                raise CloudError("云端未返回内容（连接可能被中断），请重试")
    except _StreamAborted:
        raise
    except CloudError:
        raise
    except TimeoutError as e:  # socket.timeout 在 Py3.10+ 即 TimeoutError
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise CloudError("云端响应超时（60s 无输出），请重试") from e
    except (OSError, http.client.HTTPException) as e:
        if cancelled is not None and cancelled():
            raise _StreamAborted from e
        raise CloudError(f"云端流式传输中断：{type(e).__name__}: {e}") from e
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

    def submit(self, item: tuple[int, str | None, list[dict[str, str]] | None]) -> None:
        self._q.put(item)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            conn = self._inflight
            self._inflight = None
        if conn is not None:
            # close 可能等待读流锁；不能让停止按钮或新请求阻塞 GUI。
            threading.Thread(target=self._abort_connection, args=(conn,),
                             name=f"llm-cancel-{self._kind}", daemon=True).start()

    @staticmethod
    def _abort_connection(conn: http.client.HTTPConnection) -> None:
        try:
            if conn.sock is not None:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _attach_conn(self, conn: http.client.HTTPConnection) -> None:
        with self._lock:
            self._inflight = conn
            cancelled = self._cancel_requested
        if cancelled:
            self._abort_connection(conn)

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
            req_id, text, messages = item
            try:
                if not self._is_current(req_id):
                    continue  # 排队期间已被取代/取消
                with self._lock:
                    self._cancel_requested = False

                if text is None:
                    self._run_warmup()
                else:
                    self._run_request(req_id, text, messages)
            except Exception:  # noqa: BLE001 — run 本身永不抛出
                log.exception("LLM worker(%s) 任务异常", self._kind)
            finally:
                with self._lock:
                    self._inflight = None
                self._q.task_done()

    def _run_warmup(self) -> None:
        try:
            stream_chat(
                self._client._cfg,
                self._kind,
                "-",
                options={"num_predict": 1},
                cancelled=lambda: self._cancel_requested,
                on_conn=self._attach_conn,
                messages=[{"role": "user", "content": "-"}],  # 不依赖业务标签的 prompts
            )
            log.info("预热/保活完成（model=%s）", self._client._cfg["model"])
            self._client.warmup_finished.emit(True, "本地模型已就绪，可以划词翻译。")
        except Exception as e:  # noqa: BLE001 — 预热失败只记日志，不打扰用户
            if isinstance(e, _StreamAborted):
                return
            log.warning("预热/保活请求失败：%s", e)
            self._client.warmup_finished.emit(False, str(e))

    def _run_request(self, req_id: int, text: str, messages: list[dict[str, str]] | None) -> None:
        def cancelled() -> bool:
            return self._is_cancelled(req_id)

        def on_chunk(delta: str) -> None:
            if not cancelled():
                self._client._delivery.emit("chunk", req_id, self._kind, delta)

        try:
            full = stream_chat(
                self._client._cfg,
                self._kind,
                text,
                on_chunk=on_chunk,
                cancelled=cancelled,
                on_conn=self._attach_conn,
                messages=messages,
            )
        except _StreamAborted:
            return
        except LlmError as e:
            if cancelled():
                return
            self._client._delivery.emit("failed", req_id, self._kind, str(e))
            return
        except Exception:  # noqa: BLE001
            log.exception("LLM 未知错误")
            if not cancelled():
                self._client._delivery.emit("failed", req_id, self._kind, "未知错误，请查看日志")
            return
        if not cancelled():
            self._client._delivery.emit("finished", req_id, self._kind, full)


class LlmClient(QObject):
    _delivery = Signal(str, int, str, str)
    warmup_finished = Signal(bool, str)
    chunk = Signal(str, str)  # (kind, delta)
    finished = Signal(str, str)  # (kind, full_text)
    failed = Signal(str, str)  # (kind, error_msg)

    _wants_warmup = False  # 预热请求挂在当前 id 之外，由该开关控制有效性

    def __init__(self, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._id = {"translate": 1, "explain": 1, "chat": 1, "input": 1}
        self._id_lock = threading.Lock()
        self._delivery.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._workers = {
            "translate": _Worker(self, "translate"),
            "explain": _Worker(self, "explain"),
            "chat": _Worker(self, "chat"),
            "input": _Worker(self, "input"),
        }
        for w in self._workers.values():
            w.start()

    def _current_id(self, kind: str) -> int:
        with self._id_lock:
            return self._id[kind]

    def _deliver(self, event: str, req_id: int, kind: str, text: str) -> None:
        # 在 GUI 线程再次核对 id，排除已排入 Qt 队列的旧选区结果。
        if req_id == self._current_id(kind):
            getattr(self, event).emit(kind, text)

    def request(self, kind: str, text: str, messages: list[dict[str, str]] | None = None) -> None:
        """新请求；自动取消同 kind 的旧请求（含断流）。"""
        self.cancel(kind)
        with self._id_lock:
            self._id[kind] += 1
            rid = self._id[kind]
        snapshot = [dict(message) for message in messages] if messages is not None else None
        self._workers[kind].submit((rid, text, snapshot))

    def cancel(self, *kinds: str) -> None:
        with self._id_lock:
            for kind in kinds:
                self._id[kind] += 1  # 单调递增，不能重置到预热专用 id=0。
        for k in kinds:
            self._workers[k].cancel()

    def preheat(self) -> None:
        """启动预热与 25min 保活：一条 num_predict=1 的请求消化冷启动。"""
        # 选一个走本地的标签做预热（混合模式下 translate 可能是云端）。
        local_kind = next((k for k in self._workers if provider_for(self._cfg, k) == "ollama"), None)
        if local_kind is None:
            # 全部走云端，无需预热；保活定时器调用同样无害。
            self.warmup_finished.emit(True, "已连接云端模型，可以划词翻译。")
            return
        self._wants_warmup = True
        # warmup 用 id=0 排队执行；真实请求（id>=1）到来时它自动让位
        self._workers[local_kind].submit((_PREHEAT_ID, None, None))

    def close(self) -> None:
        self._wants_warmup = False
        self.cancel(*self._workers)
        for w in self._workers.values():
            w.cancel()
            w.submit(_SHUTDOWN)
