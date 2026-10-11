# -*- coding: utf-8 -*-
"""设置窗口：图形化选择本地大模型 / 云端 API、填写 Key、联网检索与严格离线。

改动写回共享的 cfg（模型/API/联网/离线立即生效；热键、弹窗尺寸等需重启）。
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from llm import is_loopback
from netutil import open_no_redirect

log = logging.getLogger(__name__)

MODE_LOCAL, MODE_CLOUD, MODE_HYBRID = "local", "cloud", "hybrid"
HYBRID_KINDS = {"translate": "ollama", "input": "ollama", "explain": "openai", "chat": "openai"}
DEFAULT_LOCAL_URL = "http://localhost:11434"


class SettingsWindow(QWidget):
    saved = Signal()
    models_loaded = Signal(list)
    test_result = Signal(bool, str)

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self.setWindowTitle("划译 — 设置")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 置顶，避免被划词弹窗挡住
        self.resize(580, 500)
        self.setMinimumWidth(520)
        self.models_loaded.connect(self._populate_local)
        self.test_result.connect(self._show_test_result)
        self._build()

    # —— 构建

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        mode_box = QGroupBox("使用方式")
        mv = QVBoxLayout(mode_box)
        self.rb_local = QRadioButton("本地大模型（Ollama，可离线）")
        self.rb_cloud = QRadioButton("云端 API（OpenAI 兼容）")
        self.rb_hybrid = QRadioButton("混合：翻译/输入走本地，解释/追问走云端")
        for rb in (self.rb_local, self.rb_cloud, self.rb_hybrid):
            mv.addWidget(rb)
        self.chk_offline = QCheckBox("严格离线：禁用联网检索与所有云端请求")
        mv.addWidget(self.chk_offline)
        v.addWidget(mode_box)

        self.local_box = QGroupBox("本地大模型（Ollama）")
        lf = QFormLayout(self.local_box)
        self.local_url = QLineEdit()
        lf.addRow("地址", self.local_url)
        row = QHBoxLayout()
        self.local_model = QComboBox()
        self.local_model.setEditable(True)
        row.addWidget(self.local_model, 1)
        self.btn_refresh = QPushButton("刷新模型")
        self.btn_refresh.clicked.connect(self._refresh_local_models)
        row.addWidget(self.btn_refresh)
        lf.addRow("模型", row)
        v.addWidget(self.local_box)

        self.cloud_box = QGroupBox("云端 API（OpenAI 兼容）")
        cf = QFormLayout(self.cloud_box)
        self.cloud_url = QLineEdit()
        cf.addRow("地址", self.cloud_url)
        self.cloud_model = QLineEdit()
        cf.addRow("模型", self.cloud_model)
        key_row = QHBoxLayout()
        self.cloud_key = QLineEdit()
        self.cloud_key.setEchoMode(QLineEdit.Password)
        key_row.addWidget(self.cloud_key, 1)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_cloud)
        key_row.addWidget(self.btn_test)
        cf.addRow("API Key", key_row)
        self.lbl_test = QLabel("")
        self.lbl_test.setObjectName("statusLabel")
        cf.addRow("", self.lbl_test)
        v.addWidget(self.cloud_box)

        web_box = QGroupBox("联网检索（Ollama 托管 web_search）")
        wf = QFormLayout(web_box)
        self.chk_web = QCheckBox("启用：解释/追问时先联网检索再回答")
        wf.addRow(self.chk_web)
        self.web_key = QLineEdit()
        self.web_key.setEchoMode(QLineEdit.Password)
        wf.addRow("API Key", self.web_key)
        v.addWidget(web_box)

        hint = QLabel("提示：模型 / API / 联网 / 离线改动保存后立即生效；热键、弹窗尺寸等需重启。")
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        v.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.hide)
        btns.addWidget(cancel)
        save = QPushButton("保存")
        save.clicked.connect(self._on_save)
        btns.addWidget(save)
        v.addLayout(btns)

    # —— 载入 / 保存

    def open_window(self) -> None:
        self.reload()
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def reload(self) -> None:
        c = self._cfg
        kp = c.get("kind_providers") or {}
        if kp.get("explain") == "openai":
            mode = MODE_HYBRID
        elif c.get("provider") == "openai":
            mode = MODE_CLOUD
        else:
            mode = MODE_LOCAL
        self.rb_local.setChecked(mode == MODE_LOCAL)
        self.rb_cloud.setChecked(mode == MODE_CLOUD)
        self.rb_hybrid.setChecked(mode == MODE_HYBRID)
        self.chk_offline.setChecked(bool(c.get("offline")))

        self.local_url.setText(c.get("base_url") or DEFAULT_LOCAL_URL)
        self.local_model.setCurrentText(c.get("model") or "")
        cloud = c.get("cloud") or {}
        self.cloud_url.setText(cloud.get("base_url") or "")
        self.cloud_model.setText(cloud.get("model") or "")
        self.cloud_key.setText(cloud.get("api_key") or "")
        ws = c.get("web_search") or {}
        self.chk_web.setChecked(bool(ws.get("enabled")))
        self.web_key.setText(ws.get("api_key") or "")
        self.lbl_test.setText("")
        self._refresh_local_models()

    def _mode(self) -> str:
        if self.rb_cloud.isChecked():
            return MODE_CLOUD
        if self.rb_hybrid.isChecked():
            return MODE_HYBRID
        return MODE_LOCAL

    def _on_save(self) -> None:
        c = self._cfg
        c["offline"] = bool(self.chk_offline.isChecked())
        mode = self._mode()
        if mode == MODE_LOCAL:
            c["provider"], c["kind_providers"] = "ollama", {}
        elif mode == MODE_CLOUD:
            c["provider"], c["kind_providers"] = "openai", {}
        else:
            c["provider"], c["kind_providers"] = "openai", dict(HYBRID_KINDS)
        c["base_url"] = self.local_url.text().strip() or DEFAULT_LOCAL_URL
        c["model"] = self.local_model.currentText().strip()
        cloud = c.setdefault("cloud", {})
        cloud["base_url"] = self.cloud_url.text().strip()
        cloud["model"] = self.cloud_model.text().strip()
        cloud["api_key"] = self.cloud_key.text().strip()
        ws = c.setdefault("web_search", {})
        ws["enabled"] = bool(self.chk_web.isChecked())
        ws["api_key"] = self.web_key.text().strip()
        self.saved.emit()
        self.hide()

    # —— 本地模型列表 / 云端连通性测试

    def _refresh_local_models(self) -> None:
        base = self.local_url.text().strip().rstrip("/") or DEFAULT_LOCAL_URL
        if self._cfg.get("offline") and not is_loopback(urllib.parse.urlparse(base).hostname or ""):
            self.models_loaded.emit([])  # 离线：不向非本机地址查询
            return
        url = base + "/api/tags"

        def run() -> None:
            if self._cfg.get("offline") and not is_loopback(urllib.parse.urlparse(base).hostname or ""):
                self.models_loaded.emit([])  # 排队期间开启离线：发送前再检查
                return
            names: list[str] = []
            try:
                with open_no_redirect(url, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                names = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
            except Exception:  # noqa: BLE001 — 取不到就不填充，保留手输
                log.debug("拉取本地模型列表失败", exc_info=True)
            self.models_loaded.emit(names)

        threading.Thread(target=run, name="ollama-models", daemon=True).start()

    def _populate_local(self, names: list) -> None:
        current = self.local_model.currentText()
        self.local_model.clear()
        self.local_model.addItems([str(n) for n in names])
        if current:
            self.local_model.setCurrentText(current)
        elif names:
            self.local_model.setCurrentIndex(0)

    def _test_cloud(self) -> None:
        if self._cfg.get("offline"):
            self._show_test_result(False, "离线模式已开启，禁止云端连接测试")
            return
        self.lbl_test.setText("测试中…")
        self.lbl_test.setStyleSheet("")
        self.btn_test.setEnabled(False)
        base = self.cloud_url.text().strip().rstrip("/")
        model = self.cloud_model.text().strip()
        key = self.cloud_key.text().strip()

        def run() -> None:
            if self._cfg.get("offline"):  # 排队期间开启离线：发送前再检查
                self.test_result.emit(False, "离线模式已开启，禁止云端连接测试")
                return
            ok, msg = False, ""
            try:
                body = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1, "stream": False,
                }).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                req = urllib.request.Request(base + "/chat/completions", data=body,
                                             method="POST", headers=headers)
                with open_no_redirect(req, timeout=12) as resp:
                    resp.read()
                ok, msg = True, "连接成功"
            except urllib.error.HTTPError as e:
                ok, msg = False, f"HTTP {e.code}（检查地址 / 模型 / Key）"
            except Exception as e:  # noqa: BLE001
                ok, msg = False, f"失败：{e}"
            self.test_result.emit(ok, msg)

        threading.Thread(target=run, name="cloud-test", daemon=True).start()

    def _show_test_result(self, ok: bool, msg: str) -> None:
        self.btn_test.setEnabled(True)
        self.lbl_test.setText(msg)
        self.lbl_test.setStyleSheet("color:#8ecbf5;" if ok else "color:#ff8a80;")
