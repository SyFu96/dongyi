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
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
import win32gui

import capture
import llm
import startup
from conversation import CHAT_PROMPT, build_messages
from instance import SingleInstance
from popup import (
    ICON_SIZE,
    PopupWindow,
    Toast,
    TrayIcon,
    StatusWindow,
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
    "show_startup_window": False,
    "auto_start_ollama": True,
    "max_text_len": 3000,
    "debounce_ms": 150,
    "icon_timeout_s": 3,
    "hotkeys": {
        "translate": "<ctrl>+<alt>+<shift>+t",
        "explain": "<ctrl>+<alt>+<shift>+e",
    },
    "prompts": {
        "chat": CHAT_PROMPT,
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
        self._icon_sel: capture.Selection | None = None
        self._icon_anchor: tuple[int, int] = (0, 0)
        self._last_attempt: tuple[int, int] | None = None
        self._chat_history: list[dict[str, str]] = []
        self._chat_pending_question: str | None = None
        self._last_question: str | None = None
        self._ollama_start_attempted = False

        self.bridge = CaptureBridge(self)
        self.worker = capture.CaptureWorker(cfg, emit_result=self.bridge.captured.emit)
        self.llm = llm.LlmClient(cfg, self)
        self.monitor = Monitor(cfg)
        self.icon = IconWindow(cfg)
        self.popup = PopupWindow(cfg)
        self.toast = Toast()
        self.status = StatusWindow()
        self.status.test_requested.connect(self.test_translation)
        self.status.quit_requested.connect(self.quit)
        self.tray = TrayIcon(actions={
            "show_status": self.status.show_status,
            "pause": self.toggle_pause,
            "open_config": self.open_config_file,
            "autostart_enabled": startup.is_enabled(),
            "set_autostart": self.set_autostart,
            "exit": self.quit,
        }, parent=self)

        self._debounce = QTimer(self, singleShot=True, interval=int(cfg.get("debounce_ms", 150)))
        self._debounce.timeout.connect(self._fire_debounced)
        self._keepalive = QTimer(self, interval=25 * 60 * 1000)
        self._keepalive.timeout.connect(self.llm.preheat)
        self._startup_retry = QTimer(self, singleShot=True, interval=15000)
        self._startup_retry.timeout.connect(self._startup)

        self.monitor.selection_attempt.connect(self.on_attempt)
        self.monitor.hotkey.connect(self.on_hotkey)
        self.monitor.esc.connect(self.on_esc)
        self.monitor.mouse_down.connect(self.on_mouse_down)
        self.bridge.captured.connect(self.on_captured)
        self.icon.clicked.connect(self.on_icon_clicked)
        self.popup.switch_requested.connect(self.on_switched)
        self.popup.retry_requested.connect(self.on_retry)
        self.popup.stop_requested.connect(self.on_stop)
        self.popup.close_requested.connect(self.close_popup)
        self.popup.question_submitted.connect(self.on_question)
        self.llm.chunk.connect(self.on_chunk)
        self.llm.finished.connect(self.on_finished)
        self.llm.failed.connect(self.on_failed)
        self.llm.warmup_finished.connect(self.on_warmup_finished)

    # —— 启动 / 退出

    def start(self) -> None:
        QApplication.instance().setStyleSheet(app_theme_qss(self._cfg["theme"]))
        self.tray.show()
        self.worker.start()
        self.monitor.start()
        if self._cfg.get("show_startup_window", False):
            self.status.show_status()
        QTimer.singleShot(0, self._startup)

    def _startup(self) -> None:
        if not self._keepalive.isActive():
            self._keepalive.start()
        checker = OllamaChecker(self)
        checker.checked.connect(self._on_ollama_checked)
        checker.checked.connect(checker.deleteLater)
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
        if ok:
            self._startup_retry.stop()
            self.llm.preheat()
        else:
            self._start_local_ollama()
            self.status.set_model_status(False, "等待本地翻译服务启动，将自动重试…")
            self.tray.setToolTip("划译 — 等待 Ollama 启动")
            self._startup_retry.start()

    def _start_local_ollama(self) -> None:
        if self._ollama_start_attempted or not self._cfg.get("auto_start_ollama", True):
            return
        address = urllib.parse.urlparse(self._cfg["base_url"])
        if address.hostname not in ("localhost", "127.0.0.1", "::1") or address.port != 11434:
            return
        self._ollama_start_attempted = True
        executable = shutil.which("ollama")
        if not executable:
            candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.exists():
                executable = str(candidate)
        if not executable:
            log.warning("未找到 Ollama，等待用户启动本地服务")
            return
        try:
            with (APP_DIR / "ollama.log").open("a", encoding="utf-8") as output:
                subprocess.Popen(
                    [executable, "serve"], cwd=APP_DIR, stdout=output, stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            log.info("已在后台启动本地 Ollama 服务")
        except OSError:
            log.exception("后台启动 Ollama 失败")

    def on_warmup_finished(self, ok: bool, message: str) -> None:
        self.status.set_model_status(ok, message)
        self.tray.setToolTip("划译 — 本地模型已就绪" if ok else "划译 — 本地模型暂不可用")
        if not ok:
            self._startup_retry.start()

    def test_translation(self) -> None:
        self.close_popup()
        self._sel = capture.Selection(text="The battery stores energy.", source="demo")
        x, y = cursor_physical()
        self._icon_anchor = (x + 12, y + 12)
        self._open_popup("translate")

    def quit(self) -> None:
        log.info("退出划译")
        try:
            self.monitor.stop()
            self.worker.stop()
            self._startup_retry.stop()
            self._keepalive.stop()
            self.llm.cancel("translate", "explain", "chat")
            self.llm.close()
        finally:
            QApplication.instance().quit()

    # —— 托盘动作

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.status.listener_status.setText("监听已暂停" if self._paused else "监听已开启")
        self.tray.set_paused(self._paused)
        x, y = cursor_physical()
        self.toast.show_at(x, y, "已暂停监听" if self._paused else "已恢复监听")
        if self._paused:
            self.icon.hide()

    def open_config_file(self) -> None:
        os.startfile(CONFIG_PATH)  # noqa: S606 — 用户托盘操作

    def set_autostart(self, enabled: bool) -> None:
        try:
            startup.set_enabled(enabled)
            log.info("开机自启动：%s", enabled)
        except Exception:
            log.exception("修改开机自启动失败")
            self.tray.act_autostart.blockSignals(True)
            self.tray.act_autostart.setChecked(startup.is_enabled())
            self.tray.act_autostart.blockSignals(False)
            self.tray.showMessage("划译", "开机自启动设置失败，请查看日志。")

    def _inside_own_ui(self, phys: tuple[int, int]) -> bool:
        lx, ly, _ = logical_from_physical(*phys)
        return any(window.isVisible() and window.frameGeometry().contains(int(lx), int(ly))
                   for window in (self.popup, self.status, self.icon, self.toast))

    # —— 触发路径

    def on_attempt(self, info: dict) -> None:
        """划选候选（拖选松开/双击/三击）：防抖后再取词。"""
        if self._paused:
            return
        if self._inside_own_ui(info["phys"]):
            return
        self._last_attempt = info["phys"]
        self._debounce.start()

    def _fire_debounced(self) -> None:
        phys = self._last_attempt or cursor_physical()
        self._last_attempt = None
        if self._paused or self._inside_own_ui(phys):
            return
        self.icon.hide()  # 新候选：浮标先收，等取词成功再浮
        self._icon_sel = None
        self.worker.submit("silent", "icon", phys, int(self._cfg["max_text_len"]))

    def on_hotkey(self, kind: str) -> None:
        """热键兜底路径：explicit 取词（UIA → 剪贴板兜底）。"""
        if self._paused:
            return
        phys = cursor_physical()
        foreground_pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            win32gui.GetForegroundWindow(), ctypes.byref(foreground_pid)
        )
        if foreground_pid.value == os.getpid():
            return
        self._debounce.stop()
        self.worker.submit("explicit", kind, phys, int(self._cfg["max_text_len"]))

    def on_captured(self, payload: dict) -> None:
        req = payload["req"]
        sel = payload["sel"]
        purpose = req["purpose"]

        if purpose == "icon":
            if sel is None:
                self.icon.hide()  # 防误触核心：取不到就不出现任何 UI
                self._icon_sel = None
                return
            # 候选选区与正在阅读/追问的原文分开；点击新“译”后才切换。
            self._icon_sel = sel
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
            self.llm.cancel("translate", "explain", "chat")
        if sel.rect:
            self._icon_anchor = (sel.rect[0] + sel.rect[2] + 8, sel.rect[1] + sel.rect[3] + 8)
        else:
            phys = req.get("phys") or cursor_physical()
            self._icon_anchor = (phys[0] + 12, phys[1] + 12)
        self._open_popup(kind=purpose)

    def on_icon_clicked(self) -> None:
        if self._icon_sel is None:
            return
        self._sel = self._icon_sel
        self._open_popup(kind="translate")

    def _open_popup(self, kind: str) -> None:
        sel = self._sel
        if sel is None:
            return
        self.icon.hide()
        self._icon_sel = None
        self.llm.cancel("translate", "explain", "chat")
        self._chat_history.clear()
        self._chat_pending_question = None
        self._last_question = None
        ax, ay = self._icon_anchor
        self.popup.open_at(
            ax - 12, ay + ICON_SIZE + 12, sel.text, sel.truncated, initial_kind=kind,
        )
        self.llm.request(kind, sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())
        log.info("弹窗打开（kind=%s, source=%s）", kind, sel.source)

    def on_switched(self, kind: str) -> None:
        """首次切到某标签（惰性请求解释）。"""
        if self._sel is None:
            return
        self.llm.request(kind, self._sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())

    def on_retry(self, kind: str) -> None:
        if self._sel is None:
            return
        if kind == "chat":
            if self._last_question:
                self._start_question(self._last_question, retry=True)
            return
        self.popup.reset_result(kind)
        self.llm.request(kind, self._sel.text)
        self.popup.mark_pending(kind, t0=time.perf_counter())

    def on_question(self, question: str) -> None:
        self._start_question(question)

    def _start_question(self, question: str, retry: bool = False) -> None:
        if self._sel is None or self._chat_pending_question is not None or not question.strip():
            return
        question = question.strip()[:2000]
        messages = build_messages(
            self._cfg, self._sel.text, self.popup.result_text("translate"),
            self.popup.result_text("explain"), self._chat_history, question,
        )
        self._last_question = question
        self._chat_pending_question = question
        self.popup.begin_question(question, retry=retry)
        self.popup.mark_pending("chat", t0=time.perf_counter())
        self.llm.request("chat", question, messages=messages)
        log.info("追问请求已发送（history_turns=%s）", len(self._chat_history) // 2)

    # —— 关闭/取消

    def on_stop(self, kind: str) -> None:
        if not self.popup.is_pending(kind):
            return
        self.llm.cancel(kind)
        self.popup.mark_stopped(kind)
        if kind == "chat" and self._chat_pending_question is not None:
            partial = self.popup.result_text("chat")
            self._chat_history.extend([
                {"role": "user", "content": self._chat_pending_question},
                {"role": "assistant", "content": partial + "\n[用户已停止生成，本轮回答未完成。]"},
            ])
            self._chat_history = self._chat_history[-24:]
            self._chat_pending_question = None
        log.info("用户停止生成（kind=%s）", kind)

    def on_esc(self) -> None:
        if self.popup.isVisible() and not self.popup.is_pinned():
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
        if self.popup.isVisible() and not self.popup.is_pinned():
            self.close_popup()
        self.icon.hide()

    def close_popup(self) -> None:
        self.popup.close_now()
        self.llm.cancel("translate", "explain", "chat")
        self._chat_pending_question = None

    # —— LLM 信号 → 弹窗

    def on_chunk(self, kind: str, delta: str) -> None:
        if self.popup.isVisible():
            self.popup.append_chunk(kind, delta)

    def on_finished(self, kind: str, full_text: str) -> None:
        self._startup_retry.stop()
        self.status.set_model_status(True, "本地模型已就绪，可以划词翻译。")
        self.tray.setToolTip("划译 — 本地模型已就绪")
        if kind == "chat" and self._chat_pending_question is not None:
            self._chat_history.extend([
                {"role": "user", "content": self._chat_pending_question},
                {"role": "assistant", "content": full_text},
            ])
            self._chat_history = self._chat_history[-24:]
            self._chat_pending_question = None
        log.info("翻译请求完成（kind=%s, chars=%s）", kind, len(full_text))
        if self.popup.isVisible():
            self.popup.mark_done(kind)

    def on_failed(self, kind: str, msg: str) -> None:
        if kind == "chat":
            self._chat_pending_question = None
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

    instance = SingleInstance(APP_DIR, app)
    if not instance.acquire():
        log.info("划译已在后台运行")
        return
    controller = App(cfg)
    instance.activated.connect(lambda: log.info("忽略重复启动，保留当前后台实例"))
    app.aboutToQuit.connect(instance.close)
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("划译启动失败")
        # pythonw 没有控制台；启动异常必须能让桌面用户看见。
        ctypes.windll.user32.MessageBoxW(
            None, f"划译启动失败，请查看日志：\n{LOG_PATH}", "划译", 0x10
        )
        raise
