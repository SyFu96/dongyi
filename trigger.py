# -*- coding: utf-8 -*-
"""M2 触发：拖选/双击检测、热键兜底、浮标窗。

坑 4（钩子回调阻塞）：pynput 回调内只投递事件，取词/HTTP 全部由 app 在其他线程做。
跨线程到 Qt 主线程：经 Signal（自动 queued）。
"""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import QObject, Signal
from pynput import mouse as m
from pynput.keyboard import GlobalHotKeys, HotKey, Key

from popup import IconWindow

log = logging.getLogger(__name__)

DRAG_MIN_PX = 12      # 拖选判定：位移 ≥ 12 物理像素
CLICK_MAX_PX = 6      # 多击判定：位移 < 6px
MAX_CLICK_GAP = 0.4   # 多击判定：距上次 < 400ms


class Monitor(QObject):
    """全局鼠标 + 键盘监听；只发信号，不做任何耗时工作。"""

    selection_attempt = Signal(dict)  # {'phys': (x,y), 'action': 'drag'|'multi'}
    hotkey = Signal(str)              # kind ∈ {'translate','explain'}
    esc = Signal()
    mouse_down = Signal(dict)         # {'phys': (x,y), 'button': str}

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._down_pos: tuple | None = None
        self._up_pos: tuple | None = None
        self._up_t = 0.0

        hotkeys_cfg = cfg.get("hotkeys") or {}
        mapped: dict[str, object] = {}
        for kind in ("translate", "explain"):
            descr = hotkeys_cfg.get(kind)
            if not descr:
                continue
            try:
                HotKey.parse(descr)  # 先校验，避免单个坏热键弄挂整个监听
            except Exception:  # noqa: BLE001
                log.error("热键描述无法解析：%s（kind=%s）", descr, kind)
                continue
            mapped[descr] = (lambda k=kind: self.hotkey.emit(k))
        self._keys = _KeyListener(self, mapped)
        self._mouse = m.Listener(on_click=self._on_click)

    def start(self) -> None:
        try:
            self._keys.start()
        except Exception:  # noqa: BLE001
            log.exception("键盘监听启动失败")
        try:
            self._mouse.start()
        except Exception:  # noqa: BLE001
            log.exception("鼠标监听启动失败")

    def stop(self) -> None:
        for listener in (self._keys, self._mouse):
            try:
                listener.stop()
            except Exception:  # noqa: BLE001
                pass

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if pressed:
            # 任何按键按下都通知 app（用于关闭弹窗/浮标）
            self.mouse_down.emit({"phys": (x, y), "button": getattr(button, "name", "")})
        if button != m.Button.left:
            return
        now = time.perf_counter()
        if pressed:
            if self._up_pos and (now - self._up_t) <= MAX_CLICK_GAP and _dist(self._up_pos, (x, y)) <= CLICK_MAX_PX:
                self.selection_attempt.emit({"phys": (x, y), "action": "multi"})
            self._down_pos = (x, y)
        else:
            self._up_pos = (x, y)
            self._up_t = now
            if self._down_pos and _dist(self._down_pos, (x, y)) >= DRAG_MIN_PX:
                self.selection_attempt.emit({"phys": (x, y), "action": "drag"})
            self._down_pos = None


class _KeyListener(GlobalHotKeys):
    """热键 + Esc（全局关闭弹窗）。

    覆写 _on_press：先处理 Esc，再走热键状态机。
    injected 事件（我们自己模拟的 Ctrl+C）会被 GlobalHotKeys 基类忽略。
    """

    def __init__(self, owner: Monitor, hotkeys: dict) -> None:
        self._owner = owner
        super().__init__(hotkeys)

    def _on_press(self, key, injected) -> None:
        try:
            if not injected and key == Key.esc:
                self._owner.esc.emit()
        except Exception:  # noqa: BLE001
            log.exception("Esc 事件处理失败")
        super()._on_press(key, injected)


def _dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
