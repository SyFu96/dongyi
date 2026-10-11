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

import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
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
import domains
import knowledge
import llm
import netutil
import search
import startup
import tm
from conversation import CHAT_PROMPT, build_messages
from instance import SingleInstance
from popup import (
    ICON_SIZE,
    PopupWindow,
    TmEditDialog,
    Toast,
    TrayIcon,
    StatusWindow,
    app_theme_qss,
    logical_from_physical,
)
from trigger import Monitor, IconWindow
from settings import SettingsWindow

APP_DIR = Path(__file__).resolve().parent
def _writable_data_dir() -> Path:
    """找一个可写的数据目录：优先 AppData，其次系统临时目录，最后 exe 目录。

    目录解析与创建全程受保护，任何一步失败都不会在导入阶段抛出。
    """
    candidates: list[str | None] = [os.environ.get("APPDATA")]
    try:
        candidates.append(tempfile.gettempdir())  # 自身也可能抛异常
    except Exception:  # noqa: BLE001
        pass
    for base in candidates:
        if not base:
            continue
        d = Path(base) / "huayi"
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except Exception:  # noqa: BLE001
            continue
    return Path(sys.executable).resolve().parent  # 兜底：即使只读也不再抛出


if getattr(sys, "frozen", False):
    # 打包成 exe 后：程序目录通常只读，配置/日志改写到可写的数据目录。
    DATA_DIR = _writable_data_dir()
else:
    DATA_DIR = APP_DIR
CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = DATA_DIR / "app.log"

log = logging.getLogger("huayi")

DEFAULTS = {
    "provider": "ollama",  # "ollama"（本地）| "openai"（任意 OpenAI 兼容云端）
    "kind_providers": {},  # 按标签覆盖 provider，如 {"translate": "ollama"}（混合模式）
    "offline": False,  # true = 严格离线：强制全部走本机、禁用联网检索、拒绝云端请求
    "base_url": "http://localhost:11434",
    "model": "qwen3-vl:30b-a3b-instruct",
    "keep_alive": "30m",
    "cloud": {  # provider="openai" 时使用；api_key 也可用环境变量注入
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "api_key_env": "",  # 留空时读 OPENAI_API_KEY；可改为如 DEEPSEEK_API_KEY
    },
    "web_search": {  # 联网检索（Ollama 托管），仅用于解释/追问；需 api_key 或 OLLAMA_API_KEY
        "enabled": False,
        "endpoint": "https://ollama.com/api/web_search",
        "api_key": "",
        "max_results": 5,
    },
    "prefetch_explain": False,
    "show_startup_window": False,
    "auto_start_ollama": True,
    "max_text_len": 3000,
    "debounce_ms": 150,
    "icon_timeout_s": 3,
    "hotkeys": {
        "translate": "<ctrl>+<alt>+<shift>+t",
        "explain": "<ctrl>+<alt>+<shift>+e",
        "input": "<ctrl>+<alt>+<shift>+i",
    },
    "prompts": {
        "chat": CHAT_PROMPT,
        "translate": "你是划词翻译引擎。自动识别语言：非中文译为中文，中文译为英文。"
                      "只输出译文，保留换行与格式，不要任何解释。",
        "explain": "解释用户划选的文本。若是专有名词/术语/缩写：给出全称与通行中文名、所属领域、"
                   "一句话定义、2-3条关键背景或常见误读；若是句子/段落：解释其含义，外语内容附语法要点。"
                   "不确定之处明确说明，禁止编造。中文回复。",
    },
    # —— 领域适配（学科模式）——
    # domains 在 load_config 时按需种入 SEED_DOMAINS（用户删掉后不会复活）；
    # 每个领域：name 显示名 / note 追加到 system prompt 的领域说明 /
    # glossary_file 术语表 CSV / kb_dirs 知识库目录 / kb_* 检索开关。
    "domains": {},
    "active_domain": "",  # 激活领域 id；空 = 通用模式
    "tm_enabled": True,   # 翻译记忆：翻译时参考已确认的相似句对
    "blacklist_processes": [],
    "theme": "dark",
    "popup": {"width": 460, "height": 320},
}

# 内置示例领域（首次运行/旧配置升级时种入，可直接改删）
SEED_DOMAINS = {
    "battery": {
        "name": "电池/能源",
        "note": "当前文本属于电池与能源领域（锂离子电池、储能、电化学）。"
                "按该领域学术惯例翻译：材料与器件名保留通行英文缩写（如 SEI、SOC、CE）"
                "并在首次出现时附中文全称；术语译法严格遵守下方术语对照。",
        "enabled": True,
        "glossary_file": "glossaries/battery.csv",
        "kb_dirs": [],
        "kb_enabled": False,
        "kb_for_translate": False,
    },
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
                # 旧配置升级：种入示例领域；用户显式写过 "domains"（哪怕空对象）则尊重现状
                if "domains" not in data:
                    cfg["domains"] = copy.deepcopy(SEED_DOMAINS)
        except Exception:  # noqa: BLE001 — 坏配置文件也能跑（用默认值）
            log.warning("解析 config.json 失败，使用默认配置", exc_info=True)
    else:
        try:
            initial = dict(DEFAULTS)
            initial["domains"] = copy.deepcopy(SEED_DOMAINS)
            CONFIG_PATH.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")
            cfg["domains"] = copy.deepcopy(SEED_DOMAINS)
        except Exception:  # noqa: BLE001
            log.warning("写入默认 config.json 失败", exc_info=True)
    return cfg


def seed_builtin_glossaries() -> None:
    """打包版首次运行：把内置示例术语表复制到数据目录（已存在则跳过）。

    源码运行时 DATA_DIR == APP_DIR，本函数自动短路。
    """
    builtin = APP_DIR / "glossaries"
    target = DATA_DIR / "glossaries"
    if builtin == target or not builtin.is_dir():
        return
    for src in builtin.glob("*.csv"):
        dst = target / src.name
        if dst.exists():
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            log.info("已复制内置术语表：%s", dst)
        except OSError:
            log.warning("复制内置术语表失败：%s", src, exc_info=True)


def save_config(cfg: dict) -> None:
    """把当前配置写回 config.json（运行时开关持久化用）。"""
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — 写失败不影响运行
        log.warning("写入 config.json 失败", exc_info=True)


def setup_logging() -> None:
    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 日志文件不可写也不应阻止启动
        pass
    if sys.stderr is not None and not sys.executable.lower().endswith("pythonw.exe"):
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
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


class SearchBridge(QObject):
    finished = Signal(int, object)  # (seq, results)；结果为空表示检索失败/无结果


class KbBridge(QObject):
    status = Signal(str)  # 后台索引线程 → 设置页状态回写（跨线程走队列连接）


class _SearchTask:
    """一次联网检索：可取消（发送前检查 + 关闭响应中断读取）。"""

    def __init__(self, seq: int, kind: str) -> None:
        self.seq = seq
        self.kind = kind
        self._cancel = threading.Event()
        self._resp = None
        self._lock = threading.Lock()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def attach(self, resp) -> None:
        with self._lock:
            self._resp = resp
            cancelled = self._cancel.is_set()
        if cancelled:
            self._close_resp(resp)  # 已在检索线程内，直接关闭无碍

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            resp, self._resp = self._resp, None
        if resp is not None:
            # close() 可能等待对端读取结束；放到后台线程，避免阻塞 GUI。
            threading.Thread(target=self._close_resp, args=(resp,),
                             name="search-cancel", daemon=True).start()

    @staticmethod
    def _close_resp(resp) -> None:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass


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
        self._last_input: tuple[str, object] | None = None
        self._ollama_start_attempted = False
        self._search_id = 0
        self._web_latest: dict[str, int] = {}
        self._pending_web: dict[int, tuple[str, str]] = {}
        self._search_tasks: dict[int, _SearchTask] = {}

        self.bridge = CaptureBridge(self)
        self.web = SearchBridge(self)
        self.web.finished.connect(self._on_search_done)
        self.kb_bridge = KbBridge(self)
        self.worker = capture.CaptureWorker(cfg, emit_result=self.bridge.captured.emit)
        self.llm = llm.LlmClient(cfg, self)
        self.monitor = Monitor(cfg)
        self.icon = IconWindow(cfg)
        self.kb = knowledge.KnowledgeStore(DATA_DIR / "kb_index", exclude=[
            CONFIG_PATH,          # 含云端/检索密钥，绝不索引（防随提示词外发）
            DATA_DIR / "kb_index",
            DATA_DIR / "glossaries",  # 术语表本来就按命中注入，索引它只会重复
            DATA_DIR / "tm",
            DATA_DIR / "app.log",
            DATA_DIR / "ollama.log",
        ])
        self.tmstore = tm.TmStore(DATA_DIR / "tm")
        self._kb_busy = False
        self._kb_pending_dirs: list[str] | None = None  # 索引忙时暂存的最新目录集合
        self._kb_pending_lock = threading.Lock()
        self._kb_dirs_signature: tuple[str, ...] = ()
        self.popup = PopupWindow(cfg)
        self.popup.input_requested.connect(self.on_input_translate)
        self.popup.tab_changed.connect(self._update_backend_label)
        self.popup.domain_changed.connect(self.set_domain)
        self.popup.tm_save_requested.connect(self.on_tm_save)
        self.toast = Toast()
        self.status = StatusWindow()
        self.status.test_requested.connect(self.test_translation)
        self.status.input_requested.connect(self.open_input_translation)
        self.status.settings_requested.connect(self.open_settings)
        self.status.quit_requested.connect(self.quit)
        self.settings = SettingsWindow(cfg, DATA_DIR, self.kb, self.tmstore)
        self.settings.saved.connect(self.on_settings_saved)
        self.settings.rebuild_requested.connect(self.on_kb_rebuild)
        self.kb_bridge.status.connect(self.settings.set_kb_status)
        self.tray = TrayIcon(actions={
            "show_status": self.open_status,
            "open_input": self.open_input_translation,
            "open_settings": self.open_settings,
            "pause": self.toggle_pause,
            "web_search_enabled": self._web_enabled(),
            "set_web_search": self.set_web_search,
            "domain_items": self._domain_pairs,
            "active_domain": lambda: domains.resolve_active(self._cfg),
            "set_domain": self.set_domain,
            "open_config": self.open_config_file,
            "autostart_enabled": startup.is_enabled(),
            "set_autostart": self.set_autostart,
            "exit": self.quit,
        }, parent=self)
        active = domains.resolve_active(self._cfg)
        pairs = self._domain_pairs()
        self.popup.set_domains(pairs, active)
        self.tray.set_domains(pairs, active)

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
        self._maybe_refresh_kb()  # 有知识库目录时后台增量刷新索引
        if self._cfg.get("show_startup_window", False):
            self.status.show_status()
        QTimer.singleShot(0, self._startup)

    def _needs_local(self) -> bool:
        """只要有一个标签走本地（或严格离线），就需要本地 Ollama 就绪。"""
        if self._cfg.get("offline"):
            return True
        return any(llm.provider_for(self._cfg, k) == "ollama"
                   for k in ("translate", "explain", "chat", "input"))

    def _startup(self) -> None:
        if not self._keepalive.isActive():
            self._keepalive.start()
        if not self._needs_local():
            # 全云端：无需探测/启动本地服务，直接标记就绪。
            self.llm.preheat()
            log.info("划译已启动（provider=%s, model=%s）",
                     self._cfg.get("provider"), (self._cfg.get("cloud") or {}).get("model"))
            return
        checker = OllamaChecker(self)
        checker.checked.connect(self._on_ollama_checked)
        checker.checked.connect(checker.deleteLater)
        threading.Thread(target=lambda: checker.checked.emit(self._probe_ollama()),
                         name="ollama-check", daemon=True).start()
        log.info("划译已启动（provider=%s, model=%s）", self._cfg.get("provider"), self._cfg["model"])

    def _probe_ollama(self) -> bool:
        if self._cfg.get("offline"):
            host = urllib.parse.urlparse(self._cfg.get("base_url") or "").hostname or ""
            if not llm.is_loopback(host):
                log.warning("离线模式：base_url 非本机，跳过探测（不发送任何请求）")
                return False
        try:
            with netutil.open_no_redirect(self._cfg["base_url"].rstrip("/") + "/api/tags", timeout=3):
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
            with (DATA_DIR / "ollama.log").open("a", encoding="utf-8") as output:
                subprocess.Popen(
                    [executable, "serve"], cwd=APP_DIR, stdout=output, stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            log.info("已在后台启动本地 Ollama 服务")
        except OSError:
            log.exception("后台启动 Ollama 失败")

    def on_warmup_finished(self, ok: bool, message: str) -> None:
        self.status.set_model_status(ok, message)
        self.tray.setToolTip("划译 — 模型已就绪" if ok else "划译 — 模型暂不可用")
        if not ok:
            self._startup_retry.start()

    def test_translation(self) -> None:
        self.close_popup()
        self._sel = capture.Selection(text="The battery stores energy.", source="demo")
        x, y = cursor_physical()
        self._icon_anchor = (x + 12, y + 12)
        self._open_popup("translate")

    # —— 输入翻译（弹窗第 4 个标签）

    def _input_prompt(self, target) -> str:
        if target:
            return (f"你是翻译引擎。把用户输入的内容翻译成{target}。"
                    "只输出译文，保留换行与格式，不要任何解释。")
        return self._cfg["prompts"]["translate"]  # 自动：中↔英

    def open_input_translation(self) -> None:
        """呼出输入翻译：弹窗已开就切到该标签，否则在光标处打开。"""
        QTimer.singleShot(0, self._open_input_translation)

    def _open_input_translation(self) -> None:
        if self.popup.isVisible():
            self.popup.show_input_tab()
            return
        # 全新会话：清空旧讨论对象与历史，避免切到"解释/追问"时沿用旧原文
        self._sel = None
        self._chat_history.clear()
        self._chat_pending_question = None
        self._last_question = None
        self._last_input = None
        self._cancel_web()
        self.llm.cancel("translate", "explain", "chat", "input")
        x, y = cursor_physical()
        self.popup.open_at(x - 12, y + 12, "", False, initial_kind="input")
        self._update_backend_label("input")

    # —— 设置

    def open_settings(self) -> None:
        # 从托盘原生菜单直接 show() Qt 窗口会被菜单抢占而显示失败，延迟到菜单关闭后再弹。
        QTimer.singleShot(0, self._show_settings)

    def open_status(self) -> None:
        QTimer.singleShot(0, self.status.show_status)

    def _show_settings(self) -> None:
        try:
            self.settings.open_window()
        except Exception:  # noqa: BLE001
            log.exception("打开设置窗口失败")

    def on_settings_saved(self) -> None:
        save_config(self._cfg)
        self._cancel_web()  # 策略可能变化：作废在途检索
        if self._cfg.get("offline"):
            self.llm.cancel("translate", "explain", "chat", "input")  # 立即中断可能的外发
        self.tray.act_web.blockSignals(True)
        self.tray.act_web.setChecked(self._web_enabled())
        self.tray.act_web.blockSignals(False)
        # 领域配置可能增删改：同步弹窗/托盘的学科选项与激活状态
        active = domains.resolve_active(self._cfg)
        pairs = self._domain_pairs()
        self.popup.set_domains(pairs, active)
        self.tray.set_domains(pairs, active)
        self._update_backend_label()
        self._maybe_refresh_kb()
        if self._needs_local():
            self.llm.preheat()
        log.info("设置已保存（provider=%s, offline=%s, domains=%s）",
                 self._cfg.get("provider"), self._cfg.get("offline"), len(pairs) - 1)

    def on_input_translate(self, text: str, target) -> None:
        messages = [
            {"role": "system",
             "content": self._compose_system("input", text, base=self._input_prompt(target))},
            {"role": "user", "content": text},
        ]
        self._last_input = (text, target)
        # 输入文本成为当前讨论对象：随后"解释/追问"都围绕它进行
        self._sel = capture.Selection(text=text, source="input")
        self._chat_history.clear()
        self._chat_pending_question = None
        self._last_question = None
        self._cancel_web()
        self.llm.cancel("translate", "explain", "chat", "input")
        self.popup.begin_source(text)
        self.popup.reset_result("input")
        self.popup.mark_pending("input", t0=time.perf_counter())
        self.llm.request("input", text, messages=messages)
        self._update_backend_label("input")
        log.info("输入翻译请求（target=%s, chars=%s）", target, len(text))

    def quit(self) -> None:
        log.info("退出划译")
        try:
            self.monitor.stop()
            self.worker.stop()
            self._startup_retry.stop()
            self._keepalive.stop()
            self.llm.cancel("translate", "explain", "chat", "input")
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

    def _web_enabled(self) -> bool:
        if self._cfg.get("offline"):
            return False  # 严格离线：禁用联网检索
        ws = self._cfg.get("web_search") or {}
        return bool(ws.get("enabled")) and search.has_key(ws)

    def set_web_search(self, enabled: bool) -> None:
        ws = self._cfg.setdefault("web_search", {})
        if enabled and self._cfg.get("offline"):
            self.tray.act_web.blockSignals(True)
            self.tray.act_web.setChecked(False)
            self.tray.act_web.blockSignals(False)
            self.tray.showMessage("划译 — 离线模式", "已开启离线模式（offline=true），联网检索不可用。")
            return
        if enabled and not search.has_key(ws):
            # 无 key：回弹开关并提示配置方式，避免"开了却一直检索失败"。
            self.tray.act_web.blockSignals(True)
            self.tray.act_web.setChecked(False)
            self.tray.act_web.blockSignals(False)
            ws["enabled"] = False
            self.tray.showMessage(
                "划译 — 无法联网",
                "请在 config.json 的 web_search.api_key 填写 Ollama API key，"
                "或设置环境变量 OLLAMA_API_KEY 后重启。",
            )
            return
        ws["enabled"] = enabled
        save_config(self._cfg)  # 持久化，重启后仍生效
        if not enabled:
            self._cancel_web()  # 关闭联网：作废在途检索
        self._update_backend_label()
        if enabled:
            self.tray.showMessage(
                "划译 — 联网查询已开启",
                "解释会把原文、追问会把本轮问题发送到 ollama.com 检索；敏感内容请关闭此开关。",
            )
        log.info("联网查询：%s", enabled)

    # —— 领域适配（学科模式）

    def _domain_pairs(self) -> list[tuple[str, str]]:
        """弹窗/托盘的学科选项：[(id, 显示名)]，通用恒在首位。"""
        return [("", "通用")] + [
            (did, dom.get("name") or did) for did, dom in domains.enabled_domains(self._cfg)
        ]

    def set_domain(self, domain_id: str) -> None:
        """切换激活领域：写配置并持久化，同步弹窗/托盘，下次请求即生效。"""
        if domain_id and not any(did == domain_id
                                 for did, _ in domains.enabled_domains(self._cfg)):
            domain_id = ""
        if domain_id == domains.resolve_active(self._cfg):
            return
        self._cfg["active_domain"] = domain_id
        save_config(self._cfg)
        pairs = self._domain_pairs()
        self.popup.set_domains(pairs, domain_id)
        self.tray.set_domains(pairs, domain_id)
        self._update_backend_label()
        name = next((n for d, n in pairs if d == domain_id), domain_id)
        x, y = cursor_physical()
        self.toast.show_at(x, y, f"学科：{name}")
        log.info("切换学科：%s", name)

    def _compose_system(self, kind: str, text: str, base: str | None = None,
                        search_context: str = "") -> str:
        """统一组装 system prompt：

        基础 prompts[kind] → 领域说明 → 术语对照 → 知识库片段 → 参考译例(TM) → 联网检索
        各段存在才拼；领域段只在激活了领域时追加，翻译记忆通用模式也生效。
        """
        if base is None:
            base = self._cfg["prompts"][kind]
        parts = [base]
        dom = domains.active_domain(self._cfg)
        if dom is not None:
            did = domains.resolve_active(self._cfg)
            note = domains.domain_note_text(dom)
            if note:
                parts.append(note)
            glossary = domains.matched_glossary_text(DATA_DIR, did, dom, text)
            if glossary:
                parts.append(glossary)
            kb_context = knowledge.context_for(self.kb, dom, kind, text)
            if kb_context:
                parts.append(kb_context)
        if self._cfg.get("tm_enabled", True) and kind in ("translate", "input"):
            tm_context = self.tmstore.example_context(
                domains.resolve_active(self._cfg), text)
            if tm_context:
                parts.append(tm_context)
        if search_context:
            parts.append(search_context)
        return "\n\n".join(part for part in parts if part)

    def _chat_domain_context(self) -> str:
        """追问的领域上下文：领域说明 + 原文命中的术语（不检索 KB/TM，避免噪音）。"""
        dom = domains.active_domain(self._cfg)
        if dom is None:
            return ""
        parts = [domains.domain_note_text(dom)]
        if self._sel is not None:
            did = domains.resolve_active(self._cfg)
            parts.append(domains.matched_glossary_text(DATA_DIR, did, dom, self._sel.text))
        return "\n\n".join(part for part in parts if part)

    def on_tm_save(self, kind: str) -> None:
        """弹窗「存为记忆」：编辑译文后写入当前领域的翻译记忆。

        - 只接受 translate/input（explain 页没有按钮，这里再校验一次防信号误接）；
        - 原文与领域在打开对话框前快照固定：exec() 的嵌套事件循环期间可能
          收到新取词结果，不能用保存时刻的 _sel 去配旧译文。
        """
        if kind not in ("translate", "input") or self._sel is None:
            return
        translation = self.popup.result_text(kind)
        if not translation.strip():
            x, y = cursor_physical()
            self.toast.show_at(x, y, "当前没有可保存的译文")
            return
        source = self._sel.text
        did = domains.resolve_active(self._cfg)
        dialog = TmEditDialog(source, translation)
        if dialog.exec() != TmEditDialog.Accepted:
            return
        if self.tmstore.append(did, source, dialog.translation()):
            x, y = cursor_physical()
            self.toast.show_at(x, y, "已存入翻译记忆")
            log.info("翻译记忆已保存（domain=%s）", did or "general")

    def _kb_dirs_all(self) -> list[str]:
        """所有已启用领域声明的知识库目录并集（索引按并集建一次）。"""
        out: list[str] = []
        for _, dom in domains.enabled_domains(self._cfg):
            if dom.get("kb_enabled"):
                out.extend(d for d in (dom.get("kb_dirs") or []) if d)
        return sorted(set(out))

    def _maybe_refresh_kb(self, force: bool = False) -> None:
        """知识库目录集合变化时后台增量刷新索引。"""
        dirs = self._kb_dirs_all()
        signature = tuple(dirs)
        if not force and signature == self._kb_dirs_signature:
            return
        self._kb_dirs_signature = signature
        if not dirs and not force:
            return
        self._refresh_kb_async(dirs)

    def _refresh_kb_async(self, dirs: list[str]) -> None:
        """后台刷新索引；已有任务在跑时把最新目录集合暂存，任务结束后补跑，
        保证索引忙期间发生的目录变更不会丢失。"""
        if self._kb_busy:
            with self._kb_pending_lock:
                self._kb_pending_dirs = dirs
            return
        self._kb_busy = True

        def run() -> None:
            try:
                current = dirs
                while current is not None:
                    try:
                        stats = self.kb.refresh(current)
                        log.info("知识库索引完成：%s", stats)
                    except Exception:  # noqa: BLE001 — 索引失败不影响翻译主流程
                        log.exception("知识库索引刷新失败")
                        break
                    # 取走补跑意图（GUI 线程可能在上一轮期间写入了新目录）
                    with self._kb_pending_lock:
                        current, self._kb_pending_dirs = self._kb_pending_dirs, None
            finally:
                self._kb_busy = False

        threading.Thread(target=run, name="kb-refresh", daemon=True).start()

    def on_kb_rebuild(self, dirs: list | None = None) -> None:
        """设置页「重建索引」：后台重建并回写状态。

        dirs 来自设置页的工作副本（可能尚未保存），直接用它刷新——索引只是
        缓存，提前索引未保存目录没有副作用。
        """
        if self._kb_busy:
            with self._kb_pending_lock:
                self._kb_pending_dirs = list(dirs or [])
            self.settings.set_kb_status("索引进行中，新请求已排队…")
            return
        dirs = list(dirs) if dirs else self._kb_dirs_all()
        if not dirs:
            self.settings.set_kb_status("请先为领域添加知识库目录并启用")
            return
        self.settings.set_kb_status("正在重建索引…")
        self._kb_busy = True
        self._kb_dirs_signature = tuple(dirs)

        def run() -> None:
            try:
                stats = self.kb.refresh(dirs)
                summary = (f"索引完成：{stats['files']} 个文件 · {stats['chunks']} 个片段"
                           f"（新解析 {stats['parsed']}，失败 {stats['errors']}）")
                log.info("知识库索引完成：%s", stats)
            except Exception as e:  # noqa: BLE001
                summary = f"索引失败：{e}"
                log.exception("知识库索引重建失败")
            finally:
                self._kb_busy = False
            self.kb_bridge.status.emit(summary)  # 跨线程信号 → GUI 线程回写

        threading.Thread(target=run, name="kb-rebuild", daemon=True).start()

    # —— 后端/地址显示

    def _backend_text(self, kind: str) -> str:
        dom = domains.active_domain(self._cfg)
        prefix = f"{dom.get('name') or '?'} · " if dom else ""
        if self._cfg.get("offline"):
            return prefix + "离线模式（仅本地）"
        if llm.provider_for(self._cfg, kind) == "openai":
            cloud = self._cfg.get("cloud") or {}
            host = urllib.parse.urlparse(cloud.get("base_url") or "").hostname or "?"
            txt = f"云端 · {cloud.get('model') or '?'} · {host}"
        else:
            txt = f"本地 · {self._cfg.get('model') or '?'}"
        if kind in ("explain", "chat") and self._web_enabled():
            txt += " · 联网"
        return prefix + txt

    def _update_backend_label(self, kind: str | None = None) -> None:
        self.popup.set_backend(self._backend_text(kind or self.popup.current_kind()))

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
        """热键路径：input 直接呼出输入翻译窗；translate/explain 走取词兜底。"""
        if kind == "input":
            self.open_input_translation()
            return
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
            self.llm.cancel("translate", "explain", "chat", "input")
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
        self.llm.cancel("translate", "explain", "chat", "input")
        self._cancel_web()
        self._chat_history.clear()
        self._chat_pending_question = None
        self._last_question = None
        ax, ay = self._icon_anchor
        self.popup.open_at(
            ax - 12, ay + ICON_SIZE + 12, sel.text, sel.truncated, initial_kind=kind,
        )
        self._update_backend_label(kind)
        self._dispatch(kind)
        log.info("弹窗打开（kind=%s, source=%s）", kind, sel.source)

    def _dispatch(self, kind: str) -> None:
        """解释在联网开启时先检索；其余（译文/chat 由 _start_question 处理）直接请求。"""
        if kind == "explain" and self._web_enabled():
            self._begin_web(kind, self._sel.text)
        else:
            self._request_kind(kind)

    def _request_kind(self, kind: str, search_context: str = "") -> None:
        if self._sel is None:
            return
        messages = [
            {"role": "system",
             "content": self._compose_system(kind, self._sel.text, search_context=search_context)},
            {"role": "user", "content": self._sel.text},
        ]
        self.llm.request(kind, self._sel.text, messages=messages)
        self.popup.mark_pending(kind, t0=time.perf_counter())

    def on_switched(self, kind: str) -> None:
        """首次切到某标签（惰性请求解释）。"""
        if self._sel is None:
            return
        self._dispatch(kind)

    def on_retry(self, kind: str) -> None:
        if kind == "input":
            if self._last_input:
                self.on_input_translate(*self._last_input)
            return
        if self._sel is None:
            return
        if kind == "chat":
            if self._last_question:
                self._start_question(self._last_question, retry=True)
            return
        self.popup.reset_result(kind)
        self._dispatch(kind)

    def on_question(self, question: str) -> None:
        self._start_question(question)

    def _start_question(self, question: str, retry: bool = False) -> None:
        if self._sel is None or self._chat_pending_question is not None or not question.strip():
            return
        question = question.strip()[:2000]
        self._last_question = question
        self._chat_pending_question = question
        self.popup.begin_question(question, retry=retry)
        if self._web_enabled():
            self._begin_web("chat", question)
        else:
            self._request_chat(question)
        log.info("追问请求已发送（history_turns=%s）", len(self._chat_history) // 2)

    def _request_chat(self, question: str, search_context: str = "") -> None:
        if self._sel is None:
            return
        translation = self.popup.result_text("translate")
        if not translation and self._sel.source == "input":
            translation = self.popup.result_text("input")  # 输入翻译的译文也进入追问上下文
        messages = build_messages(
            self._cfg, self._sel.text, translation,
            self.popup.result_text("explain"), self._chat_history, question, search_context,
            domain_context=self._chat_domain_context(),
        )
        self.popup.mark_pending("chat", t0=time.perf_counter())
        self.llm.request("chat", question, messages=messages)

    # —— 联网检索（解释/追问）

    def _begin_web(self, kind: str, query: str) -> None:
        """后台检索，完成后由 _on_search_done 发起 LLM 请求。"""
        self._search_id += 1
        seq = self._search_id
        task = _SearchTask(seq, kind)
        self._search_tasks[seq] = task
        self._web_latest[kind] = seq
        self._pending_web[seq] = (kind, query)
        self.popup.mark_pending(kind, t0=time.perf_counter(), label="联网检索中…")
        threading.Thread(target=self._run_search, args=(seq, query, task),
                         name="web-search", daemon=True).start()

    def _run_search(self, seq: int, query: str, task: "_SearchTask") -> None:
        if not self._web_enabled():  # 发送前再次核对策略（离线/已关闭）
            self.web.finished.emit(seq, [])
            return
        try:
            results = search.web_search(query, self._cfg.get("web_search"),
                                        cancelled=task.cancelled, on_conn=task.attach)
        except Exception as e:  # noqa: BLE001 — 检索失败不阻塞回答，退回模型自身知识
            if not task.cancelled():
                log.warning("联网检索失败：%s", e)
            results = []
        if task.cancelled():
            results = []
        self.web.finished.emit(seq, results)

    def _on_search_done(self, seq: int, results: list) -> None:
        self._search_tasks.pop(seq, None)
        pending = self._pending_web.pop(seq, None)
        if pending is None:
            return  # 已被关闭 / 停止 / 新原文作废
        kind, question = pending
        if self._web_latest.get(kind) != seq:
            return  # 该标签已有更新的检索，本次作废（其他标签不受影响）
        context = search.format_results(results)
        if not context:
            log.info("联网检索无有效结果，按模型自身知识回答（kind=%s）", kind)
        if kind == "chat":
            if self._chat_pending_question is None:
                return
            self._request_chat(self._chat_pending_question, context)
        else:
            self._request_kind(kind, context)

    def _cancel_web(self, kind: str | None = None) -> None:
        """作废检索：kind 为 None 清空全部，否则只清该标签；中断请求并复位界面状态。"""
        if kind is None:
            affected = {k for k, _ in self._pending_web.values()}
            for task in self._search_tasks.values():
                task.cancel()
            self._search_tasks.clear()
            self._web_latest.clear()
            self._pending_web.clear()
        else:
            affected = {k for s, (k, _) in self._pending_web.items() if k == kind}
            self._web_latest.pop(kind, None)
            for seq in [s for s, (k, _) in self._pending_web.items() if k == kind]:
                task = self._search_tasks.pop(seq, None)
                if task is not None:
                    task.cancel()
                del self._pending_web[seq]
        # 复位被作废检索的界面状态，避免"联网检索中…"卡住
        for k in affected:
            if self.popup.is_pending(k):
                self.popup.mark_stopped(k)
            if k == "chat":
                self._chat_pending_question = None

    # —— 关闭/取消

    def on_stop(self, kind: str) -> None:
        if not self.popup.is_pending(kind):
            return
        self._cancel_web(kind)  # 只作废本标签的检索，避免误伤其他标签
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
        self.llm.cancel("translate", "explain", "chat", "input")
        self._cancel_web()
        self._chat_pending_question = None

    # —— LLM 信号 → 弹窗

    def on_chunk(self, kind: str, delta: str) -> None:
        if self.popup.isVisible():
            self.popup.append_chunk(kind, delta)

    def on_finished(self, kind: str, full_text: str) -> None:
        self._startup_retry.stop()
        self.status.set_model_status(True, "模型已就绪，可以划词翻译。")
        self.tray.setToolTip("划译 — 模型已就绪")
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
    seed_builtin_glossaries()
    provider = cfg.get("provider", "ollama")
    model = (cfg.get("cloud") or {}).get("model") if provider == "openai" else cfg.get("model")
    log.info("启动：provider=%s model=%s", provider, model)

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
