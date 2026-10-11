# -*- coding: utf-8 -*-
"""设置窗口：本地/云端/离线、联网检索，以及「领域与知识库」学科适配管理。

改动写回共享的 cfg（模型/API/联网/离线/领域立即生效；热键、弹窗尺寸等需重启）。
领域配置在打开窗口时深拷贝为工作副本，保存时整体写回（取消则丢弃）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

import domains
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
    # 「重建索引」携带工作副本中的知识库目录（可能尚未保存），由 App 后台执行并回写状态
    rebuild_requested = Signal(list)

    def __init__(self, cfg: dict, data_dir: Path | None = None,
                 kb_store=None, tm_store=None) -> None:
        super().__init__()
        self._cfg = cfg
        self._data_dir = data_dir or Path.cwd()
        self._kb = kb_store
        self._tm = tm_store
        self._domains: dict = {}
        self._loading_form = False  # 表单载入期间阻断控件信号回写工作副本
        self.setWindowTitle("划译 — 设置")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 置顶，避免被划词弹窗挡住
        self.resize(640, 880)
        self.setMinimumWidth(560)
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

        v.addWidget(self._build_domain_box())

        hint = QLabel("提示：模型 / API / 联网 / 离线 / 领域改动保存后立即生效；热键、弹窗尺寸等需重启。")
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

    def _build_domain_box(self) -> QGroupBox:
        box = QGroupBox("领域与知识库（学科适配）")
        dv = QVBoxLayout(box)
        dv.setSpacing(6)

        row = QHBoxLayout()
        self.domain_combo = QComboBox()
        self.domain_combo.currentIndexChanged.connect(
            lambda _index: self._load_domain_form())
        row.addWidget(self.domain_combo, 1)
        self.btn_domain_new = QPushButton("新建")
        self.btn_domain_new.clicked.connect(self._new_domain)
        row.addWidget(self.btn_domain_new)
        self.btn_domain_del = QPushButton("删除")
        self.btn_domain_del.clicked.connect(self._delete_domain)
        row.addWidget(self.btn_domain_del)
        dv.addLayout(row)

        form = QFormLayout()
        self.domain_name = QLineEdit()
        self.domain_name.textChanged.connect(self._sync_form_to_work)
        form.addRow("名称", self.domain_name)
        self.domain_note = QPlainTextEdit()
        self.domain_note.setMaximumHeight(72)
        self.domain_note.setPlaceholderText(
            "追加到提示词的领域说明，如：这是电池领域文献，请按学术惯例翻译……")
        self.domain_note.textChanged.connect(self._sync_form_to_work)
        form.addRow("领域说明", self.domain_note)
        self.domain_enabled = QCheckBox("启用（出现在弹窗与托盘的学科切换中）")
        self.domain_enabled.toggled.connect(self._sync_form_to_work)
        form.addRow(self.domain_enabled)
        dv.addLayout(form)

        glo_row = QHBoxLayout()
        self.lbl_glossary = QLabel("术语表：0 条")
        self.lbl_glossary.setObjectName("statusLabel")
        glo_row.addWidget(self.lbl_glossary, 1)
        self.btn_glo_new = QPushButton("新建空表")
        self.btn_glo_new.clicked.connect(self._new_glossary)
        glo_row.addWidget(self.btn_glo_new)
        self.btn_glo_edit = QPushButton("编辑术语表")
        self.btn_glo_edit.clicked.connect(self._edit_glossary)
        glo_row.addWidget(self.btn_glo_edit)
        dv.addLayout(glo_row)

        self.chk_kb = QCheckBox("启用知识库：解释时注入个人文档中的相关片段")
        self.chk_kb.toggled.connect(self._sync_form_to_work)
        dv.addWidget(self.chk_kb)
        self.chk_kb_translate = QCheckBox("翻译 / 输入翻译时也检索知识库（略增延迟）")
        self.chk_kb_translate.toggled.connect(self._sync_form_to_work)
        dv.addWidget(self.chk_kb_translate)

        kb_row = QHBoxLayout()
        self.kb_dirs = QListWidget()
        self.kb_dirs.setMaximumHeight(72)
        self.kb_dirs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        kb_row.addWidget(self.kb_dirs, 1)
        kb_btns = QVBoxLayout()
        self.btn_kb_add = QPushButton("添加目录")
        self.btn_kb_add.clicked.connect(self._add_kb_dir)
        kb_btns.addWidget(self.btn_kb_add)
        self.btn_kb_remove = QPushButton("移除所选")
        self.btn_kb_remove.clicked.connect(self._remove_kb_dir)
        kb_btns.addWidget(self.btn_kb_remove)
        self.btn_kb_rebuild = QPushButton("重建索引")
        self.btn_kb_rebuild.clicked.connect(self._rebuild_kb)
        kb_btns.addWidget(self.btn_kb_rebuild)
        kb_btns.addStretch(1)
        kb_row.addLayout(kb_btns)
        dv.addLayout(kb_row)
        self.lbl_kb_status = QLabel("")
        self.lbl_kb_status.setObjectName("statusLabel")
        self.lbl_kb_status.setWordWrap(True)
        dv.addWidget(self.lbl_kb_status)

        tm_row = QHBoxLayout()
        self.chk_tm = QCheckBox("翻译记忆：翻译时自动参考已确认的相似句对")
        tm_row.addWidget(self.chk_tm, 1)
        self.btn_tm_clear = QPushButton("清空本领域记忆")
        self.btn_tm_clear.clicked.connect(self._clear_tm)
        tm_row.addWidget(self.btn_tm_clear)
        dv.addLayout(tm_row)
        self.lbl_tm_count = QLabel("")
        self.lbl_tm_count.setObjectName("statusLabel")
        dv.addWidget(self.lbl_tm_count)
        return box

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

        self._domains = deepcopy(c.get("domains") or {})
        self._load_domain_combo(c.get("active_domain") or None)
        self.chk_tm.setChecked(bool(c.get("tm_enabled", True)))

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
        # 领域与知识库
        self._sync_form_to_work()
        c["domains"] = self._domains
        c["tm_enabled"] = bool(self.chk_tm.isChecked())
        if c.get("active_domain") and c["active_domain"] not in self._domains:
            c["active_domain"] = ""  # 领域已被删除：回退通用
        self.saved.emit()
        self.hide()

    # —— 领域表单

    def _current_domain_id(self) -> str:
        return self.domain_combo.currentData() or ""

    def _load_domain_combo(self, active: str | None = None) -> None:
        self.domain_combo.blockSignals(True)
        self.domain_combo.clear()
        seen: set[str] = set()
        # 按 config 插入顺序去重（与运行时 enabled_domains 的保留者一致），
        # 大小写别名不进 UI——否则别名条目能借"清空/计数"动到保留领域的翻译记忆
        for did, dom in self._domains.items():
            if not (domains.valid_id(did) and isinstance(dom, dict)):
                continue
            key = did.lower()
            if key in seen:
                log.warning("领域 id %s 与已有领域仅大小写不同，设置页不显示该别名", did)
                continue
            seen.add(key)
            self.domain_combo.addItem((dom.get("name") or did), did)
        self.domain_combo.blockSignals(False)
        if active:
            for i in range(self.domain_combo.count()):
                if self.domain_combo.itemData(i) == active:
                    self.domain_combo.setCurrentIndex(i)
                    break
        self._load_domain_form()

    def _load_domain_form(self) -> None:
        did = self._current_domain_id()
        has = bool(did)
        # 载入期间阻断回写：setText/setChecked 会触发 textChanged/toggled，
        # 若不阻断，先设置的控件会把"尚未载入的旧值"写回正在载入的领域配置
        # （典型后果：切换领域后 kb_dirs 被上一个领域的目录污染）。
        self._loading_form = True
        try:
            for widget in (self.domain_name, self.domain_note, self.domain_enabled,
                           self.chk_kb, self.chk_kb_translate, self.btn_glo_new,
                           self.btn_glo_edit, self.btn_kb_add, self.btn_kb_remove,
                           self.btn_kb_rebuild, self.btn_tm_clear, self.kb_dirs):
                widget.setEnabled(has)
            if not has:
                self.domain_name.clear()
                self.domain_note.clear()
                self.domain_enabled.setChecked(False)
                self.chk_kb.setChecked(False)
                self.chk_kb_translate.setChecked(False)
                self.kb_dirs.clear()
                self.lbl_glossary.setText("还没有领域：点「新建」创建一个（如 医学、法律）。")
                self.lbl_kb_status.setText("")
                self.lbl_tm_count.setText("")
                return
            dom = self._domains.get(did) or {}
            self.domain_name.setText(dom.get("name") or "")
            self.domain_note.setPlainText(dom.get("note") or "")
            self.domain_enabled.setChecked(bool(dom.get("enabled", True)))
            self.chk_kb.setChecked(bool(dom.get("kb_enabled")))
            self.chk_kb_translate.setChecked(bool(dom.get("kb_for_translate")))
            self.kb_dirs.clear()
            for d in dom.get("kb_dirs") or []:
                self.kb_dirs.addItem(str(d))
        finally:
            self._loading_form = False
        self._refresh_domain_status()

    def _sync_form_to_work(self, *_args) -> None:
        """表单任何改动立即写入工作副本，切选/保存时不丢编辑。"""
        if self._loading_form:
            return
        did = self._current_domain_id()
        if not did:
            return
        dom = self._domains.setdefault(did, {})
        dom["name"] = self.domain_name.text().strip() or did
        dom["note"] = self.domain_note.toPlainText().strip()
        dom["enabled"] = bool(self.domain_enabled.isChecked())
        dom["kb_enabled"] = bool(self.chk_kb.isChecked())
        dom["kb_for_translate"] = bool(self.chk_kb_translate.isChecked())
        dom["kb_dirs"] = [self.kb_dirs.item(i).text() for i in range(self.kb_dirs.count())]

    def _refresh_domain_status(self) -> None:
        did = self._current_domain_id()
        if not did:
            return
        path = self._glossary_path()
        if path is not None:
            count = len(domains.load_glossary(path))
            self.lbl_glossary.setText(f"术语表：{count} 条 · {path}")
        dirs = [self.kb_dirs.item(i).text() for i in range(self.kb_dirs.count())]
        if self._kb is not None and dirs:
            stats = self._kb.stats(dirs)
            self.lbl_kb_status.setText(
                f"知识库索引：{stats['files']} 个文件 · {stats['chunks']} 个片段")
        else:
            self.lbl_kb_status.setText("知识库索引：未建立（添加目录并保存后自动构建）")
        if self._tm is not None:
            self.lbl_tm_count.setText(f"本领域翻译记忆：{self._tm.count(did)} 条")

    def _new_domain(self) -> None:
        text, ok = QInputDialog.getText(self, "新建领域", "领域名称（如：医学、法律、中医）：")
        if not ok or not text.strip():
            return
        name = text.strip()[:30]
        n = 1
        while f"d{n}" in self._domains:
            n += 1
        did = f"d{n}"
        self._domains[did] = {
            "name": name, "note": "", "enabled": True, "glossary_file": "",
            "kb_dirs": [], "kb_enabled": False, "kb_for_translate": False,
        }
        self._load_domain_combo(did)

    def _delete_domain(self) -> None:
        did = self._current_domain_id()
        if not did:
            return
        dom = self._domains.get(did) or {}
        name = dom.get("name") or did
        answer = QMessageBox.question(
            self, "划译", f"删除领域「{name}」？（术语表与索引文件不会被删除）")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._domains.pop(did, None)
        self._load_domain_combo(None)

    # —— 术语表

    def _glossary_path(self) -> Path | None:
        did = self._current_domain_id()
        if not did:
            return None
        dom = self._domains.get(did) or {}
        value = (dom.get("glossary_file") or "").strip()
        if value:
            return domains.resolve_path(self._data_dir, value)
        return domains.default_glossary_path(self._data_dir, did)

    def _new_glossary(self) -> None:
        path = self._glossary_path()
        did = self._current_domain_id()
        if path is None or not did:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(
                    "# 术语表：每行 原文,译文,备注(可省略)；# 开头为注释。可直接用 Excel 编辑。\n",
                    encoding="utf-8-sig")
            try:
                value = str(path.relative_to(self._data_dir)).replace("\\", "/")
            except ValueError:
                value = str(path)
            self._domains.setdefault(did, {})["glossary_file"] = value
        except OSError:
            QMessageBox.warning(self, "划译", f"创建术语表失败：{path}")
            return
        self._edit_glossary()
        self._refresh_domain_status()

    def _edit_glossary(self) -> None:
        path = self._glossary_path()
        if path is None:
            return
        if not path.exists():
            self._new_glossary()  # 顺手创建再打开
            return
        try:
            os.startfile(path)  # noqa: S606 — 用户主动操作
        except OSError:
            QMessageBox.warning(self, "划译", f"无法打开术语表：{path}")

    # —— 知识库目录

    def _add_kb_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择知识库目录（文献/笔记所在的文件夹）")
        if not d:
            return
        existing = {self.kb_dirs.item(i).text() for i in range(self.kb_dirs.count())}
        if d not in existing:
            self.kb_dirs.addItem(d)
        self._sync_form_to_work()
        self._refresh_domain_status()

    def _remove_kb_dir(self) -> None:
        row = self.kb_dirs.currentRow()
        if row < 0:
            return
        self.kb_dirs.takeItem(row)
        self._sync_form_to_work()
        self._refresh_domain_status()

    def _rebuild_kb(self) -> None:
        self._sync_form_to_work()
        # 索引是所有领域共享的：重建必须用全部启用领域的目录并集（当前领域
        # 取表单实时值，未保存也生效），否则会把其他领域的资料从索引里挤掉
        did = self._current_domain_id()
        dirs: list[str] = []
        for dom_id, dom in self._domains.items():
            if not domains.valid_id(dom_id) or not isinstance(dom, dict):
                continue
            if dom_id == did:
                if not self.domain_enabled.isChecked() or not self.chk_kb.isChecked():
                    continue
                dirs.extend(self.kb_dirs.item(i).text()
                            for i in range(self.kb_dirs.count()))
            else:
                if not dom.get("enabled", True) or not dom.get("kb_enabled"):
                    continue
                dirs.extend(dom.get("kb_dirs") or [])
        dirs = list(dict.fromkeys(d for d in dirs if d))
        self.rebuild_requested.emit(dirs)

    def set_kb_status(self, text: str) -> None:
        """App 后台重建索引后的状态回写。"""
        self.lbl_kb_status.setText(text)

    # —— 翻译记忆

    def _clear_tm(self) -> None:
        did = self._current_domain_id()
        if not did or self._tm is None:
            return
        name = (self._domains.get(did) or {}).get("name") or did
        answer = QMessageBox.question(
            self, "划译", f"清空领域「{name}」的全部翻译记忆？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._tm.clear(did)
        self._refresh_domain_status()

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
