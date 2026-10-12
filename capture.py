# -*- coding: utf-8 -*-
"""M1 取词：UIA 读选中文本 + 受控的剪贴板兜底。

约定：
- 所有 UIA/剪贴板调用都运行在常驻捕获线程内，线程启动即 CoInitialize。
- 热键（explicit）路径：UIA 失败即走剪贴板兜底（模拟 Ctrl+C，用户显式触发）。
- 拖选（silent）路径的自动兜底：仅在 clipboard_fallback 开启且前台进程在
  clipboard_fallback_processes 白名单（默认 sioyek.exe，可自行扩充）时生效；
  黑名单进程与终端类窗口一律拒绝。发 Ctrl+C 前复查请求时效与前台窗口
  身份，请求过期或用户已切窗直接跳过。
- 兜底只在可可靠还原的剪贴板上操作（空/纯文本及其合成格式组合；图片、
  文件、HTML 等直接跳过），备份/还原用临时 message-only owner 窗口——
  MS 文档：owner=NULL 时 SetClipboardData 可能失败。
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


def _current_foreground_hwnd() -> int | None:
    """当前前台窗口句柄；取不到返回 None。供兜底前置检查与窗口身份比对。"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        return hwnd or None
    except Exception:  # noqa: BLE001
        return None


def _window_class(hwnd: int | None) -> str:
    """窗口类名；失败返回 ''。"""
    if not hwnd:
        return ""
    try:
        return win32gui.GetClassName(hwnd) or ""
    except Exception:  # noqa: BLE001
        return ""


# 集成终端窗口类：Ctrl+C 可能是复制或中断信号，统一拦在白名单之外
_TERMINAL_EXCLUDED_CLASSES = {
    "ConsoleWindowClass",            # 传统控制台
    "CASCADIA_HOSTING_WINDOW_CLASS", # Windows Terminal
    "PseudoConsoleWindow",           # conpty 宿主
}
# VSCode 等 Electron 应用类名同为 Chrome_WidgetWin_1，无法按类区分编辑器
# 与集成终端——它们不在默认白名单里，用户手动加入即自担误发风险。


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


# ---------------------------------------------------------------- 剪贴板兜底
#
# 设计约束（静默/自动路径必须满足）：
# - 发 Ctrl+C 前确认前台窗口身份与请求仍有效，过期/切窗直接跳过；
# - 只允许在"可可靠还原"的剪贴板上操作：当前为空，或仅有标准纯文本
#   格式（CF_UNICODETEXT + 系统合成的 CF_TEXT/CF_OEMTEXT/CF_LOCALE 组合，
#   见 MS clipboard-formats 文档——EnumClipboardFormats 会列出合成格式，
#   所以不能用"恰好只有一个格式"判断）；含图片/文件/注册富格式时跳过；
# - 备份/还原若失败，接受结果不可恢复（设置 static 占位），绝不猜内容；
# - 还原用本线程内临时创建的 message-only owner 窗口调 OpenClipboard(hwnd)
#   + EmptyClipboard + SetClipboardData：MS 文档明示 owner=NULL 时
#   SetClipboardData 可能失败，不能 OpenClipboard(None) 后写剪贴板。


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


def _clipboard_text(max_seq: int | None = None) -> str | None:
    """读剪贴板 CF_UNICODETEXT（带开板重试）。失败/无文本返回 None。

    max_seq 提供时把"序号核对 + 读数据"放进同一次开板窗口内：序号变化
    只说明"有人改过"，不证明就是目标应用响应 Ctrl+C，读到的内容必须与
    发键后观测到的那次序号一致才可信。
    """
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard(None)
        except Exception:  # noqa: BLE001 — 剪贴板被占用
            time.sleep(0.005)
            continue
        try:
            if max_seq is not None and _clip_seq() != max_seq:
                return None  # 序号又变了：读到的不一定是刚复制的那份，放弃
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


# 纯文本内容的合成格式组合：EnumClipboardFormats 对 CF_UNICODETEXT 通常还会
# 列出系统合成的 CF_TEXT / CF_OEMTEXT / CF_LOCALE（MS "Clipboard Formats"），
# 这些不算"另有格式"，允许静默兜底写入后按文本还原。
_TEXT_FORMAT_OK = {
    win32clipboard.CF_UNICODETEXT,   # 13
    win32clipboard.CF_TEXT,          # 1（ANSI 合成）
    win32clipboard.CF_OEMTEXT,       # 7（OEM 合成）
    win32clipboard.CF_LOCALE,        # 16（locale 合成，伴 ANSI 文本出现）
}


@dataclass
class _ClipSnapshot:
    """一次开板事务内的剪贴板备份快照。"""
    seq: int          # 事务内记录的序号（后续读结果/还原的时效基准）
    text: str | None  # 备份纯文本；"" = 空剪贴板（还原=清空）；None = 无文本/读取失败
    text_only: bool   # 空或纯文本合成组合 → 可可靠还原
    ok: bool          # False = 枚举/读取失败或剪贴板被占用（不该发键）


def _clipboard_backup_snapshot() -> _ClipSnapshot:
    """同一 OpenClipboard 事务内：枚举格式 → 读纯文本 → 记录序号。

    序号必须在**读取完成后**（关板前）记录：读备份可能触发目标应用的
    延迟渲染（GetClipboardData → WM_RENDERFORMAT → SetClipboardData），
    期间序号递增；先记 seq 会把"渲染序号"误判为 Ctrl+C 的响应，把旧
    备份内容当选区。读取失败（异常/类型异常）→ ok=False，静默不发键。
    """
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard(None)
        except Exception:  # noqa: BLE001 — 剪贴板被占用
            time.sleep(0.005)
            continue
        try:
            fmt = 0
            text_only = True
            while True:
                fmt = win32clipboard.EnumClipboardFormats(fmt)  # 0 = 枚举结束
                if fmt == 0:
                    break
                if fmt not in _TEXT_FORMAT_OK:
                    text_only = False
                    break
            text: str | None = ""  # 空剪贴板：还原语义=EmptyClipboard（还原为空）
            ok = True
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                try:
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                except Exception:  # noqa: BLE001
                    ok, text = False, None
                else:
                    if isinstance(data, str):
                        text = data
                    else:
                        ok, text = False, None
            seq = _clip_seq()  # 读取后、关板前：延迟渲染已使序号稳定
            return _ClipSnapshot(seq=seq, text=text, text_only=text_only, ok=ok)
        except Exception:  # noqa: BLE001
            return _ClipSnapshot(seq=0, text=None, text_only=False, ok=False)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # noqa: BLE001
                pass
    return _ClipSnapshot(seq=0, text=None, text_only=False, ok=False)  # 一直被占用


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


def _clipboard_owner_hwnd() -> int | None:
    """临时 message-only owner 窗口（STATIC 系统类，HWND_MESSAGE 父级）。

    空/写回剪贴板事务（OpenClipboard+Empty+Set）须持非 NULL owner：MS
    SetClipboardData 文档明示 NULL owner 时可能失败。生命周期由调用方
    管理：静默事务外层 finally 统一销毁；延迟还原线程自建自销。失败返回
    None，调用方放弃写回。
    """
    try:
        import win32con

        return win32gui.CreateWindowEx(
            0, "STATIC", "dongyi-clipboard", 0, 0, 0, 0, 0,
            win32con.HWND_MESSAGE, 0, 0, None)
    except Exception:  # noqa: BLE001
        log.debug("创建剪贴板 owner 窗口失败", exc_info=True)
        return None


def _restore_clipboard_text_sync(hwnd: int, text: str | None, expect_seq: int) -> bool:
    """持调用方的 owner HWND 写回备份；不管理 hwnd 生命周期。

    - OpenClipboard(hwnd) 成功后核对序号 == expect_seq：不等则写回会清掉
      用户新内容，跳过。text=None 跳过还原；""=只 Empty（还原为空）。
    """
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard(hwnd)
        except Exception:  # noqa: BLE001 — 被其他程序占用
            time.sleep(0.005)
            continue
        try:
            if _clip_seq() != expect_seq:
                log.debug("还原前剪贴板又被改动，跳过写回")
                return False
            if text is None:
                log.debug("无纯文本备份，跳过还原")
                return True
            win32clipboard.EmptyClipboard()
            if text:
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            return True
        except Exception:  # noqa: BLE001
            log.warning("剪贴板写回失败", exc_info=True)
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # noqa: BLE001
                pass
    log.warning("剪贴板持续被占用，未还原备份")
    return False


def _restore_clipboard_text_delayed(text: str | None, expect_seq: int) -> None:
    """350ms 延迟还原：显式热键路径保留旧行为时序（不打断用户紧接着的粘贴）。

    owner 在还原线程内创建、try/finally 同线程销毁；创建失败直接放弃写回
    （绝不 OpenClipboard(NULL)+Empty——owner 为 NULL 时 SetClipboardData
    可能失败，见 MS SetClipboardData 文档）。
    """

    def _do() -> None:
        hwnd = _clipboard_owner_hwnd()
        if not hwnd:
            log.warning("延迟还原：owner 创建失败，放弃写回")
            return
        try:
            _restore_clipboard_text_sync(hwnd, text, expect_seq)
        finally:
            try:
                win32gui.DestroyWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass

    threading.Timer(0.35, _do).start()


def _clipboard_selection(max_text_len: int, silent: bool,
                         still_valid=None) -> Selection | None:
    """模拟 Ctrl+C → 读结果 → 还原备份。

    silent=True（拖选自动）：owner 建不出、备份不可纯文本还原、still_valid
    复查失败——任一都不发键；还原同步（同一 owner，事务 finally 统一销毁）。
    silent=False（显式热键）：保留旧行为——剪贴板内容类型不设限（富格式
    只还原纯文本部分），350ms 延迟还原、owner 由还原线程自建自销毁。
    终端类窗口两条路径都跳过。still_valid：发键前复查处（最新 id + 目标
    窗口，stat 之前已完成备份），返回 False 时不发键；silent 另要求当前
    序号==备份完成时的序号（备份后被他人改过则跳过）。
    """
    try:
        fg = win32gui.GetForegroundWindow()
        cls = win32gui.GetClassName(fg)
    except Exception:  # noqa: BLE001
        cls = ""
    if cls in _TERMINAL_EXCLUDED_CLASSES:
        log.debug("终端类窗口 %s，跳过剪贴板兜底", cls or "<未知>")
        return None

    hwnd = _clipboard_owner_hwnd() if silent else None
    if silent and not hwnd:
        log.debug("owner 窗口创建失败，跳过兜底")
        return None
    try:
        snap = _clipboard_backup_snapshot()
        if not snap.ok:
            # 快照失败（占用/枚举/读取失败）：seq 基线不可用，无法判定
            # "复制成功"，继续发键只会把旧内容误报成选区——两条路径一致
            # fail-close，热键重试即可。
            log.debug("剪贴板快照失败，跳过兜底（不发键）")
            return None
        if silent and not snap.text_only:
            log.debug("剪贴板含不可纯文本还原的格式，静默跳过兜底")
            return None

        if (still_valid is not None and not still_valid()) \
                or (silent and _clip_seq() != snap.seq):
            # 复查贴着发键：最新请求+目标窗口；以及备份关闭后剪贴板未被
            # 他人改过（被改过则其变化会被下面的检测误判为 Ctrl+C 响应）
            log.debug("发键前复查失败（请求过期/切窗/备份后剪贴板已变），跳过兜底")
            return None
        _send_ctrl_c()  # 异常不吞：向外传播，owner 由 finally 清理

        deadline = time.perf_counter() + 0.3
        copied_seq = None
        while time.perf_counter() < deadline:
            seq_now = _clip_seq()
            if seq_now != snap.seq:
                copied_seq = seq_now
                break
            time.sleep(0.01)
        if copied_seq is None:
            return None  # 未复制成功：剪贴板未变，无需还原

        # 读结果与序号核对在同一开板窗口内（_clipboard_text(max_seq=...)）
        text = _clipboard_text(max_seq=copied_seq)
        if silent:
            _restore_clipboard_text_sync(hwnd, snap.text, copied_seq)
        else:
            # ""（原剪贴板为空）→ None：显式路径跳过还原，保持旧行为
            _restore_clipboard_text_delayed(snap.text or None, copied_seq)
        if not text or not text.strip():
            return None
        raw_len = len(text.strip())
        text = text.strip()
        if len(text) > max_text_len:
            text = text[:max_text_len]
        return Selection(text=text, rect=None, source="clipboard", truncated=raw_len > max_text_len)
    finally:
        if hwnd:  # 静默事务的 owner 生命周期统一归外层（延迟还原自建自销）
            try:
                win32gui.DestroyWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 对外接口


def _silent_fallback_ok(cfg: dict, fg_hwnd: int | None) -> tuple[bool, str]:
    """静默（拖选）路径是否允许自动剪贴板兜底，及不允许时的原因（供日志/测试）。

    自动兜底会向前台窗口模拟 Ctrl+C，误发面大：仅对受支持的阅读器进程
    白名单生效（默认 sioyek.exe，可在 clipboard_fallback_processes 增补）。
    黑名单进程与终端窗口类优先拒绝。要求 clipboard_fallback 总开关开启。
    """
    if not cfg.get("clipboard_fallback", True):
        return False, "disabled"
    if fg_hwnd is None:
        fg_hwnd = _current_foreground_hwnd()
    if not fg_hwnd:
        return False, "no-foreground"
    cls = _window_class(fg_hwnd)
    if cls in _TERMINAL_EXCLUDED_CLASSES:
        return False, f"terminal:{cls}"
    pname = process_name_of_hwnd(fg_hwnd)
    if not pname:
        return False, "no-process-name"
    if pname in {n.lower() for n in (cfg.get("blacklist_processes") or [])}:
        return False, f"blacklisted:{pname}"
    allow: set[str] = set()
    for n in (cfg.get("clipboard_fallback_processes") or []):
        n = str(n).strip().lower()
        if n:
            allow.add(n if "." in n else n + ".exe")  # 允许省略 .exe 后缀
    if pname not in allow:
        return False, f"not-whitelisted:{pname}"
    return True, pname


def get_selection(mode: str, max_text_len: int = 3000, cfg: dict | None = None) -> Selection | None:
    """取选中文本（供测试脚本/控制台同步调用；应用内走 CaptureWorker）。

    先 UIA；失败后：
    - mode='explicit'（热键路径）：按既有行为直接走剪贴板兜底（模拟
      Ctrl+C，备份/还原纯文本；终端窗口类跳过）。不走白名单：热键是
      用户显式动作。
    - mode='silent'（拖选路径）：自动兜底只对 _silent_fallback_ok 放行
      （clipboard_fallback 总开关 + 进程白名单 + 黑名单 + 终端排除）。
      无 cfg 时禁用自动兜底——缺配置就不做有副作用的动作。
    """
    ensure_com()
    conf = cfg if cfg is not None else {}
    sel = _uia_selection(max_text_len)
    if sel is not None:
        return sel
    if mode == "explicit":
        return _clipboard_selection(max_text_len, silent=False)
    ok, _reason = _silent_fallback_ok(conf, None)
    if ok:
        return _clipboard_selection(max_text_len, silent=True)
    return None


# ---------------------------------------------------------------- 捕获线程


class CaptureWorker(threading.Thread):
    """常驻捕获线程：串行处理取词请求，主线程防抖到期后投递任务。

    latest-id 机制：submit 时 req_id 递增；silent 请求在三个检查点被淘汰
    （出队时、自动兜底发键前、投递前），连拖多次/拖滚动条/切窗时旧请求
    自然过期，且不会把别的窗口的选区投给 GUI。锁只在读 latest_id 瞬间
    持有，绝不贯穿 UIA/剪贴板等待（否则会阻塞 GUI submit）。
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
                   "phys": phys, "max_text_len": max_text_len,
                   "target_hwnd": _current_foreground_hwnd()}  # submit 时的目标窗口
            if mode == "silent":
                # latest-id 淘汰只作用于 silent 路径；explicit（热键）永远有效
                self._latest_id = req["id"]
        self._q.put(req)
        return req["id"]

    def stop(self) -> None:
        self._q.put(None)

    def run(self) -> None:
        ensure_com()
        try:
            while True:
                job = self._q.get()
                if job is None:
                    break
                try:
                    sel = None
                    emit = True
                    if job["mode"] == "silent":
                        with self._lock:
                            if job["id"] != self._latest_id:
                                emit = False  # 出队前已被更新的请求取代
                        if emit:
                            sel, emit = self._capture_silent(job)
                        # _capture_silent 内部已完成时效/身份复查与投递决策
                    else:  # explicit
                        sel = get_selection("explicit", job["max_text_len"], cfg=self._cfg)
                    if emit:
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

    def _is_latest(self, req_id: int) -> bool:
        """短暂持锁读最新 id：绝不跨 UIA/剪贴板等待持有锁（会卡 GUI submit）。"""
        with self._lock:
            return req_id == self._latest_id

    def _capture_silent(self, job: dict) -> tuple[Selection | None, bool]:
        """拖选取词：UIA → 受限剪贴板兜底。返回 (Selection|None, 是否投递)。

        目标窗口在 submit 时固定为 target_hwnd；任务全程在出队、发键前、
        投递前三处与当前最新 id + 前台窗口核对（UIA 成功路径同样核对），
        过期/切窗一律放弃（不投递），黑名单命中仍投递 sel=None（旧行为：
        GUI 收尾隐蔽浮标）。
        """
        target = job["target_hwnd"]
        still_valid = (lambda: self._is_latest(job["id"])
                       and _current_foreground_hwnd() == target)
        pname = process_name_of_hwnd(target) if target else ""
        if pname and pname in {n.lower() for n in (self._cfg.get("blacklist_processes") or [])}:
            log.debug("进程 %s 命中黑名单，跳过静默取词", pname)
            return None, True
        if not still_valid():
            log.debug("请求已过期或前台切换，放弃静默取词")
            return None, False

        sel = _uia_selection(job["max_text_len"])
        if sel is None and still_valid():
            ok, _reason = _silent_fallback_ok(self._cfg, target)
            if ok:
                sel = _clipboard_selection(job["max_text_len"], silent=True,
                                           still_valid=still_valid)
        if not still_valid():
            return None, False  # UIA 成功路径同样核对：失败/切窗的结果不投递
        return sel, True
