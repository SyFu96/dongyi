# -*- coding: utf-8 -*-
"""划译入口：加载配置 → 检查 Ollama → 预热 → 起监听 → Qt 循环。

用 pythonw 启动（无控制台窗口），日志写 app.log：
    .venv\\Scripts\\pythonw.exe app.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

# 必须在 import capture（触发 uiautomation 导入）之前把进程 DPI 感知设为
# Per-Monitor V2：uiautomation 导入时会用 shcore.SetProcessDpiAwareness 抢先
# 占用进程感知，Qt 启动时再设就会失败并打
# "SetProcessDpiAwarenessContext() failed" 警告，多屏缩放换算也可能失准。
try:
    _user32 = ctypes.windll.user32
    _user32.SetProcessDpiAwarenessContext.restype = ctypes.c_void_p
    _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:  # noqa: BLE001 — 老系统无此 API，Qt 自会兜底
    pass

import json
import logging
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import capture
import llm
from popup import (
    ICON_SIZE,
    PopupWindow,
    Toast,
    TrayIcon,
    app_theme_qss,
    logical_from_physical,
)
from trigger import Monitor, IconWindow

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "app.log"

log = logging.getLogger("huayi")

DEFAULTS = {
    "base_url": "http://localhost:11434",
    "model": "qwen3-vl:30b-a3b-instruct",
    "keep_alive": "30m",
    "prefetch_explain": False,
    "max_text_len": 3000,
    "debounce_ms": 150,
    "icon_timeout_s": 3,
    "hotkeys": {
        "translate": "<ctrl>+<alt>+t",
        "explain": "<ctrl>+<alt>+e",
    },
    "prompts": {
        "translate": "你是划词翻译引擎。自动识别语言：非中文译为中文，中文译为英文。"
                      "只输出译文，保留换行与格式，不要任何解释。",
        "explain": "解释用户划选的文本。若是专有名词/术语/缩写：给出全称与通行中文名、所属领域、"
                   "一句话定义、2-3条关键背景或常见误读；若是句子/段落：解释其含义，外语内容附语法要点。"
                   "不确定之处明确说明，禁止编造。中文回复。",
    },
    "blacklist_processes": [],
    "theme": "dark",
    "popup": {"width": 460, "height": 320},
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    cfg = DEFAULTS.copy()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = _deep_merge(DEFAULTS, data)
        except Exception:  # noqa: BLE001 — 坏配置文件也能跑（用默认值）
            log.warning("解析 config.json 失败，使用默认配置", exc_info=True)
    else:
        try:
            CONFIG_PATH.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            log.warning("写入默认 config.json 失败", exc_info=True)
    return cfg


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr is not None and not sys.executable.lower().endswith("pythonw.exe"):
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def cursor_physical() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


# ---------------------------------------------------------------- 桥接信号


class CaptureBridge(QObject):
    captured = Signal(dict)  # {'req': {...}, 'sel': Selection|None}


class OllamaChecker(QObject):
    checked = Signal(bool)  # False → 托盘提示


# ---------------------------------------------------------------- 主编排


class App(QObject):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self._paused = False
        self._sel: capture.Selection | None = None
        self._icon_anchor: tuple[int, int] = (0, 0)
        self._last_attempt: tuple[int, int] | None = None

        self.bridge = CaptureBridge(self)
        self.worker = capture.CaptureWorker(cfg, emit_result=self.bridge.captured.emit)
        self.llm = llm.LlmClient(cfg, self)
        self.monitor = Monitor(cfg)
        self.icon = IconWindow(cfg)
        self.popup = PopupWindow(cfg)
        self.toast = Toast()
        self.tray = TrayIcon(actions={
            "pause": self.toggle_pause,
            "open_config": self.open_config_file,
            "exit": self.quit,
        }, parent=self)

        self._debounce = QTimer(self, singleShot=True, interval=int(cfg.get("debounce_ms", 150)))
        self._debounce.timeout.connect(self._fire_debounced)
        self._keepalive = QTimer(self, interval=25 * 60 * 1000)
        self._keepalive.timeout.connect(self.llm.preheat)

        self.monitor.selection_attempt.connect(self.on_attempt)
        self.monitor.hotkey.connect(self.on_hotkey)
        self.monitor.esc.connect(self.on_esc)
        self.monitor.mouse_down.connect(self.on_mouse_down)
        self.bridge.captured.connect(self.on_captured)
        self.icon.clicked.connect(self.on_icon_clicked)
        self.popup.switch_requested.connect(self.on_switched)
        self.popup.retry_requested.connect(self.on_retry)
        self.popup.close_requested.connect(self.close_popup)
        self.llm.chunk.connect(self.on_chunk)
        self.llm.finished.connect(self.on_finished)
        self.llm.failed.connect(self.on_failed)

    # —— 启动 / 退出

    def start(self) -> None:
        QApplication.instance().setStyleSheet(app_theme_qss(self._cfg["theme"]))
        self.tray.show()
        self.worker.start()
        self.monitor.start()
        QTimer.singleShot(0, self._startup)

    def _startup(self) -> None:
        self.llm.preheat()  # 启动即预热，消化冷启动
        self._keepalive.start()
        checker = OllamaChecker(self)
        checker.checked.connect(self._on_ollama_checked)
        threading.Thread(target=lambda: checker.checked.emit(self._probe_ollama()),
                         name="ollama-check", daemon=True).start()
        log.info("划译已启动（model=%s）", self._cfg["model"])

    def _probe_ollama(self) -> bool:
        try:
            with urllib.request.urlopen(self._cfg["base_url"].rstrip("/") + "/api/tags", timeout=3):
                return True
        except Exception:  # noqa: BLE001
            return False

    def _on_ollama_checked(self, ok: bool) -> None:
        if not ok:
            self.tray.showMessage(
                "划译",
                "Ollama 服务不可达，请先启动 `ollama serve`",
                QSystemTrayIcon.MessageIcon.Warning,
                timeout=4000,
            )

    def quit(self) -> None:
        log.info("退出划译")
        try:
            self.monitor.stop()
            self.worker.stop()
            self.llm.cancel("translate", "explain")
            self.llm.close()
        finally:
            QApplication.instance().quit()

    # —— 托盘动作

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.tray.set_paused(self._paused)
        x, y = cursor_physical()
        self.toast.show_at(x, y, "已暂停监听" if self._paused else "已恢复监听")
        if self._paused:
            self.icon.hide()

    def open_config_file(self) -> None:
        os.startfile(CONFIG_PATH)  # noqa: S606 — 用户托盘操作

    # —— 触发路径

    def on_attempt(self, info: dict) -> None:
        """划选候选（拖选松开/双击/三击）：防抖后再取词。"""
        if self._paused:
            return
        self._last_attempt = info["phys"]
        self._debounce.start()

    def _fire_debounced(self) -> None:
        phys = self._last_attempt or cursor_physical()
        self._last_attempt = None
        self.icon.hide()  # 新候选：浮标先收，等取词成功再浮
        self.worker.submit("silent", "icon", phys, int(self._cfg["max_text_len"]))

    def on_hotkey(self, kind: str) -> None:
        """热键兜底路径：explicit 取词（UIA → 剪贴板兜底）。"""
        if self._paused:
            return
        phys = cursor_physical()
        self.worker.submit("explicit", kind, phys, int(self._cfg["max_text_len"]))

    def on_captured(self, payload: dict) -> None:
        req = payload["req"]
        sel = payload["sel"]
        purpose = req["purpose"]

        if purpose == "icon":
            if sel is None:
                self.icon.hide()  # 防误触核心：取不到就不出现任何 UI
                return
            if self.popup.isVisible():
                self.close_popup()  # 新划译：旧弹窗关闭 + 旧请求取消
            self._sel = sel
            if sel.rect:
                self._icon_anchor = (sel.rect[0] + sel.rect[2] + 8, sel.rect[1] + sel.rect[3] + 8)
            else:
                phys = req.get("phys") or cursor_physical()
                self._icon_anchor = (phys[0] + 12, phys[1] + 12)
            self.icon.show_at(*self._icon_anchor)
            return

        # —— 热键路径（purpose ∈ {'translate','explain'}）
        if sel is None:
            x, y = req.get("phys") or cursor_physical()
            self.toast.show_at(x, y, "未取到选中文本")
            return
        self._sel = sel
        if self.popup.isVisible():
            self.llm.cancel("translate", "explain")
        if sel.rect:
            self._icon_anchor = (sel.rect[0] + sel.rect[2] + 8, sel.rect[1] + sel.rect[3] + 8)
        else:
            phys = req.get("phys") or cursor_physical()
            self._icon_anchor = (phys[0] + 12, phys[1] + 12)
        self._open_popup(kind=purpose)

    def on_icon_clicked(self) -> None:
        if self._sel is None:
            return
        self._open_popup(kind="translate")

    def _open_popup(self, kind: str) -> None:
        sel = self._sel
        if sel is None:
            return
        ax, ay = self._icon_anchor
        self.popup.open_at(
            ax - 12, ay + ICON_SIZE + 12, sel.text, sel.truncated, initial_kind=kind,
        )
        self.llm.request(kind, sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())
        log.debug("弹窗打开（kind=%s, source=%s）", kind, sel.source)

    def on_switched(self, kind: str) -> None:
        """首次切到某标签（惰性请求解释）。"""
        if self._sel is None:
            return
        self.llm.request(kind, self._sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())

    def on_retry(self, kind: str) -> None:
        if self._sel is None:
            return
        self.llm.request(kind, self._sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())

    # —— 关闭/取消

    def on_esc(self) -> None:
        if self.popup.isVisible():
            self.close_popup()
        self.icon.hide()

    def on_mouse_down(self, info: dict) -> None:
        """点击落在弹窗/浮标外 → 关闭弹窗 + 隐藏浮标 + 取消请求。"""
        lx, ly, _ = logical_from_physical(*info["phys"])
        if self.popup.isVisible():
            g = self.popup.frameGeometry()
            if g.contains(int(lx), int(ly)):
                return
        if self.icon.isVisible():
            ig = self.icon.frameGeometry()
            if ig.contains(int(lx), int(ly)):
                return  # 点击的是浮标本体 → 由浮标自己的处理
        if self.popup.isVisible():
            self.close_popup()
        self.icon.hide()

    def close_popup(self) -> None:
        self.popup.close_now()
        self.llm.cancel("translate", "explain")

    # —— LLM 信号 → 弹窗

    def on_chunk(self, kind: str, delta: str) -> None:
        if self.popup.isVisible():
            self.popup.append_chunk(kind, delta)

    def on_finished(self, kind: str, full_text: str) -> None:
        if self.popup.isVisible():
            self.popup.mark_done(kind)

    def on_failed(self, kind: str, msg: str) -> None:
        if self.popup.isVisible():
            self.popup.mark_failed(kind, msg)


def main() -> None:
    setup_logging()
    cfg = load_config()
    log.info("启动：model=%s base_url=%s", cfg["model"], cfg["base_url"])

    # RoundingPolicy 必须在创建 QApplication 之前设置（Qt6 默认 Per-Monitor V2）
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("划译")

    controller = App(cfg)
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
