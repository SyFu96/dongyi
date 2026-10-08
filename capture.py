# -*- coding: utf-8 -*-
"""M1 取词：UIA 读选中文本 + 热键路径的剪贴板兜底。

约定：
- 所有 UIA/剪贴板调用都运行在常驻捕获线程内，线程启动即 CoInitialize。
- 静默路径（拖选）永不碰剪贴板；只有热键（explicit）才走剪贴板兜底。
- 坐标一律 Windows 物理像素，与 Qt 通过 devicePixelRatio 换算对齐。
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field

import win32clipboard
import win32gui
import uiautomation as auto

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 数据结构


@dataclass
class Selection:
    text: str  # 非空、去首尾空白、超长已截断
    rect: tuple | None = None  # 选区包围盒 (l, t, w, h) 物理像素
    source: str = "uia"  # 'uia' | 'clipboard'
    truncated: bool = False


# ---------------------------------------------------------------- COM 线程管理


def ensure_com() -> None:
    """在当前线程初始化 COM（捕获线程启动时调用一次，测试脚本也可用）。"""
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001 — 已初始化等非致命错误直接忽略
        log.debug("comtypes.CoInitialize 失败", exc_info=True)
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001
        pass


def uninit_com() -> None:
    try:
        import comtypes

        comtypes.CoUninitialize()
    except Exception:  # noqa: BLE001
        pass
    try:
        import pythoncom

        pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 进程名


def process_name_of_hwnd(hwnd: int) -> str:
    """窗口句柄 → 进程名（小写，含扩展名）。失败返回 ''。"""
    if not hwnd:
        return ""
    try:
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            size = ctypes.c_ulong(512)
            buf = ctypes.create_unicode_buffer(512)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        log.debug("取进程名失败", exc_info=True)
    return ""


def foreground_process_name() -> str:
    try:
        return process_name_of_hwnd(win32gui.GetForegroundWindow())
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- UIA 取词


def _uia_selection(max_text_len: int) -> Selection | None:
    """UIA 读焦点控件的选中文本；失败返回 None，绝不抛出。"""
    try:
        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return None
        try:
            tp = ctrl.GetTextPattern()
        except Exception:  # noqa: BLE001 — COM 异常 / 无 TextPattern
            return None
        if tp is None:
            return None

        ranges = list(tp.GetSelection() or [])
        for rng in ranges:
            try:
                text = rng.GetText(-1)
            except Exception:  # noqa: BLE001
                continue
            if not text or not text.strip():
                continue

            raw_len = len(text.strip())
            text = text.strip()
            if len(text) > max_text_len:
                text = text[:max_text_len]

            rect = None
            try:
                boxes = list(rng.GetBoundingRectangles())
                if boxes:
                    l = min(b.left for b in boxes)
                    t = min(b.top for b in boxes)
                    r = max(b.right for b in boxes)
                    bt = max(b.bottom for b in boxes)
                    if r > l and bt > t:
                        rect = (int(l), int(t), int(r - l), int(bt - t))
            except Exception:  # noqa: BLE001 — 拿不到包围盒不致命
                log.debug("GetBoundingRectangles 失败", exc_info=True)

            return Selection(text=text, rect=rect, source="uia", truncated=raw_len > max_text_len)
    except Exception:  # noqa: BLE001 — 任一 UIA 异常都视作取词失败
        log.debug("UIA 取词失败", exc_info=True)
    return None


# ---------------------------------------------------------------- 剪贴板兜底（explicit 专用）


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43

_MODIFIERS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)


def _clip_seq() -> int:
    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def _clipboard_text() -> str | None:
    """读剪贴板 CF_UNICODETEXT（带开板重试）。失败/无文本返回 None。"""
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard(None)
        except Exception:  # noqa: BLE001 — 剪贴板被占用
            time.sleep(0.005)
            continue
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return data if isinstance(data, str) else None
            return None
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # noqa: BLE001
                pass
    return None


def _key(vk: int, up: bool = False) -> _INPUT:
    item = _INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki = _KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if up else 0,
        time=0,
        dwExtraInfo=None,
    )
    return item


def _held_modifiers() -> list[int]:
    user32 = ctypes.windll.user32
    return [vk for vk in _MODIFIERS if user32.GetAsyncKeyState(vk) & 0x8000]


def _send_ctrl_c() -> None:
    """SendInput 模拟 Ctrl+C：先临时释放用户按住的冲突修饰键，组合键发完再恢复原状态。"""
    user32 = ctypes.windll.user32
    held = _held_modifiers()
    items: list[_INPUT] = []
    items.extend(_key(vk, up=True) for vk in held)
    items.append(_key(VK_CONTROL))
    items.append(_key(VK_C))
    items.append(_key(VK_C, up=True))
    items.append(_key(VK_CONTROL, up=True))
    items.extend(_key(vk, up=False) for vk in reversed(held))

    arr = (_INPUT * len(items))(*items)
    user32.SendInput(len(items), arr, ctypes.sizeof(_INPUT))


def _restore_clipboard_text(text: str | None) -> None:
    """350ms 后在独立线程还原剪贴板（立即还原会干扰原应用的粘贴行为）。"""

    def _do_restore():
        time.sleep(0.35)
        for _ in range(3):
            try:
                win32clipboard.OpenClipboard(None)
            except Exception:  # noqa: BLE001
                time.sleep(0.005)
                continue
            try:
                win32clipboard.EmptyClipboard()
                if text:
                    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            except Exception:  # noqa: BLE001
                log.debug("剪贴板还原失败", exc_info=True)
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:  # noqa: BLE001
                    pass
            return

    threading.Thread(target=_do_restore, daemon=True, name="clipboard-restore").start()


def _clipboard_selection(max_text_len: int) -> Selection | None:
    """剪贴板兜底：仅热键路径调用。传统控制台直接放弃（Ctrl+C 是中断信号）。"""
    try:
        fg = win32gui.GetForegroundWindow()
        cls = win32gui.GetClassName(fg)
    except Exception:  # noqa: BLE001
        cls = ""
    if cls == "ConsoleWindowClass":
        log.debug("传统控制台窗口，跳过剪贴板兜底（Ctrl+C 是中断信号）")
        return None

    seq_before = _clip_seq()
    backed_up = _clipboard_text()
    _send_ctrl_c()

    deadline = time.perf_counter() + 0.3
    copied = False
    while time.perf_counter() < deadline:
        if _clip_seq() != seq_before:
            copied = True
            break
        time.sleep(0.01)

    if not copied:
        _restore_clipboard_text(backed_up)
        return None

    text = _clipboard_text()
    _restore_clipboard_text(backed_up)
    if not text or not text.strip():
        return None
    raw_len = len(text.strip())
    text = text.strip()
    if len(text) > max_text_len:
        text = text[:max_text_len]
    return Selection(text=text, rect=None, source="clipboard", truncated=raw_len > max_text_len)


# ---------------------------------------------------------------- 对外接口


def get_selection(mode: str, max_text_len: int = 3000) -> Selection | None:
    """取选中文本。

    mode='silent'（拖选路径）：只用 UIA，失败返回 None，绝不碰剪贴板。
    mode='explicit'（热键路径）：UIA 失败后走剪贴板兜底。

    供测试脚本同步调用；应用内走 CaptureWorker（其线程已初始化 COM）。
    """
    ensure_com()
    sel = _uia_selection(max_text_len)
    if sel is not None:
        return sel
    if mode == "explicit":
        return _clipboard_selection(max_text_len)
    return None


# ---------------------------------------------------------------- 捕获线程


class CaptureWorker(threading.Thread):
    """常驻捕获线程：串行处理取词请求，主线程防抖到期后投递任务。

    latest-id 机制：submit 时 req_id 递增；出队时若 silent 请求已不是
    最新 id 则直接丢弃（连拖多次 / 拖滚动条时旧请求自然过期）。
    """

    def __init__(self, cfg: dict, emit_result) -> None:
        super().__init__(name="capture", daemon=True)
        self._cfg = cfg
        self._emit = emit_result  # callable(payload: dict) -> None
        self._q: queue.Queue = queue.Queue()
        self._next_id = 0
        self._latest_id = 0
        self._lock = threading.Lock()

    def submit(self, mode: str, purpose: str, phys: tuple | None, max_text_len: int) -> int:
        with self._lock:
            self._next_id += 1
            req = {"id": self._next_id, "mode": mode, "purpose": purpose,
                   "phys": phys, "max_text_len": max_text_len}
            if mode == "silent":
                # latest-id 淘汰只作用于 silent 路径；explicit（热键）永远有效
                self._latest_id = req["id"]
        self._q.put(req)
        return req["id"]

    def stop(self) -> None:
        self._q.put(None)

    def run(self) -> None:
        ensure_com()
        blacklist = [n.lower() for n in (self._cfg.get("blacklist_processes") or [])]
        try:
            while True:
                job = self._q.get()
                if job is None:
                    break
                try:
                    sel = None
                    if job["mode"] == "silent":
                        with self._lock:
                            stale = job["id"] != self._latest_id
                        if stale:
                            self._q.task_done()
                            continue
                        pname = foreground_process_name()
                        if pname and pname in blacklist:
                            log.debug("进程 %s 命中黑名单，跳过静默取词", pname)
                        else:
                            sel = _uia_selection(job["max_text_len"])
                    else:  # explicit
                        sel = get_selection("explicit", job["max_text_len"])
                    self._emit({"req": job, "sel": sel})
                except Exception:  # noqa: BLE001
                    log.exception("捕获线程处理任务失败")
                    try:
                        self._emit({"req": job, "sel": None})
                    except Exception:  # noqa: BLE001
                        pass
                self._q.task_done()
        finally:
            uninit_com()
