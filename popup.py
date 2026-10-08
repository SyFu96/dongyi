# -*- coding: utf-8 -*-
"""M4 弹窗 + 托盘 + Toast，以及物理像素坐标换算、主题样式工具。

物理像素与 Qt 逻辑像素显式换算；结果展示时不抢焦点，追问时可主动输入。
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QMenu,
    QWidget,
)

log = logging.getLogger(__name__)

ICON_SIZE = 24  # 浮标边长（逻辑像素）

DARK_QSS = """
* { font-family: "Microsoft YaHei UI"; font-size: 10pt; color: #d5dade; }
#popupRoot { background: #1e2126; border: 1px solid #3a3f45; border-radius: 8px; }
QLabel { background: transparent; }
QTabWidget::pane { border: 1px solid #343a40; border-radius: 4px; top: -1px; }
QTabBar::tab { background: #262b30; color: #9aa3ab; padding: 4px 16px; }
QTabBar::tab:selected { background: #343a40; color: #f2f4f6; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }
QScrollBar::handle:vertical { background: #464e56; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolButton, QPushButton { background: #2b3138; color: #d5dade; border: 1px solid #40464d; border-radius: 4px; padding: 2px 10px; }
QToolButton:hover, QPushButton:hover { background: #363d45; }
QPushButton#retryBtn { color: #8ecbf5; }
QMenu { background: #25292e; color: #d5dade; border: 1px solid #3a3f45; }
QMenu::item { padding: 4px 24px; }
QMenu::item:selected { background: #363d45; }
QLineEdit, QPlainTextEdit { background: #25292e; color: #d5dade; border: 1px solid #40464d; border-radius: 4px; padding: 5px; }
QToolButton:checked { background: #245779; color: #e4f4ff; }
#sourceText { color: #eceff2; }
#statusLabel { color: #7f8992; }
#truncBanner { color: #ffb74d; }
"""

LIGHT_QSS = """
* { font-family: "Microsoft YaHei UI"; font-size: 10pt; color: #20242a; }
#popupRoot { background: #f5f6f8; border: 1px solid #b9bec5; border-radius: 8px; }
QLabel { background: transparent; }
QTabWidget::pane { border: 1px solid #c9ced4; border-radius: 4px; top: -1px; }
QTabBar::tab { background: #e4e7ea; color: #5c656d; padding: 4px 16px; }
QTabBar::tab:selected { background: #f5f6f8; color: #17191c; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }
QScrollBar::handle:vertical { background: #b5bbc2; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolButton, QPushButton { background: #e8ebef; border: 1px solid #b9bec5; border-radius: 4px; padding: 2px 10px; }
QToolButton:hover, QPushButton:hover { background: #dfe3e8; }
QPushButton#retryBtn { color: #0b62c4; }
QMenu { background: #ffffff; color: #20242a; border: 1px solid #b9bec5; }
QMenu::item { padding: 4px 24px; }
QMenu::item:selected { background: #dfe3e8; }
QLineEdit, QPlainTextEdit { background: #ffffff; color: #20242a; border: 1px solid #b9bec5; border-radius: 4px; padding: 5px; }
QToolButton:checked { background: #c9e5fa; color: #174d76; }
#sourceText { color: #14171a; }
#statusLabel { color: #72797f; }
#truncBanner { color: #b26a00; }
"""


def app_theme_qss(theme: str) -> str:
    return LIGHT_QSS if theme == "light" else DARK_QSS


# ---------------------------------------------------------------- 物理像素坐标工具


def screen_for_physical(px: float, py: float):
    """返回物理坐标所在的屏幕；找不到则回主屏。"""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen() or screens[0]
    for s in screens:
        dpr = s.devicePixelRatio() or 1.0
        g = s.geometry()
        if g.x() * dpr <= px < (g.x() + g.width()) * dpr and g.y() * dpr <= py < (g.y() + g.height()) * dpr:
            return s
    return primary


def logical_from_physical(px: float, py: float) -> tuple[float, float, float]:
    """物理坐标 → (逻辑x, 逻辑y, 所在屏 devicePixelRatio)。用于把钩子坐标与 Qt 窗口比对。"""
    s = screen_for_physical(px, py)
    dpr = s.devicePixelRatio() or 1.0
    return px / dpr, py / dpr, dpr


def place_window(widget: QWidget, phys_x: float, phys_y: float, offset: tuple = (0, 0)) -> None:
    """把无边框窗口放到物理坐标 + 物理像素偏移，并 clamp 进所在屏可用区域。"""
    s = screen_for_physical(phys_x, phys_y)
    dpr = s.devicePixelRatio() or 1.0
    lx = int((phys_x + offset[0]) / dpr)
    ly = int((phys_y + offset[1]) / dpr)
    avail = s.availableGeometry()
    w, h = widget.width(), widget.height()
    lx = min(max(lx, avail.left()), max(avail.left(), avail.right() - w + 1))
    ly = min(max(ly, avail.top()), max(avail.top(), avail.bottom() - h + 1))
    widget.move(lx, ly)


# ---------------------------------------------------------------- 无焦点小窗基类


class _NoFocusWindow(QWidget):
    """tool 型无边框、置顶、不抢焦点窗口基类（浮标 / Toast 共用）。"""

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)

    def mousePressEvent(self, e) -> None:  # noqa: N802 — Qt 事件覆写
        if e.button() == Qt.LeftButton:
            e.accept()
            self.hide()
            self._on_click()
        else:
            super().mousePressEvent(e)

    def _on_click(self) -> None:
        pass


class IconWindow(_NoFocusWindow):
    """选区旁的小浮标（"译"），点击后打开弹窗。"""

    clicked = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.setFixedSize(ICON_SIZE, ICON_SIZE)
        style = (
            "background:#25292e;border:1px solid #4a5158;border-radius:5px;"
            "color:#7ec3ff;font-family:'Microsoft YaHei UI';font-size:12px;font-weight:bold;"
        )
        lbl = QLabel("译", self)
        lbl.setGeometry(0, 0, ICON_SIZE, ICON_SIZE)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(style)
        self.setStyleSheet(style)

        self._hide_ms = int(float(cfg.get("icon_timeout_s", 3)) * 1000)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.hide)

    def show_at(self, phys_x: float, phys_y: float) -> None:
        """浮标出现在物理坐标处（选区右下角 +8px 等偏移已由调用方算好）。"""
        place_window(self, phys_x, phys_y)
        self.show()
        self._timer.start(self._hide_ms)
        log.debug("浮标显示 @ 物理坐标(%s, %s)", phys_x, phys_y)

    def _on_click(self) -> None:
        self.clicked.emit()


class Toast(_NoFocusWindow):
    """不抢焦点的临时提示（如"未取到选中文本"）。"""

    def __init__(self) -> None:
        super().__init__()
        self._lbl = QLabel("", self)
        self._lbl.setStyleSheet(
            "background:rgba(20,22,26,235);color:#cfd6dc;border:1px solid #3a3f45;"
            "border-radius:6px;padding:6px 14px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self._lbl)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_at(self, phys_x: float, phys_y: float, text: str, ms: int = 1500) -> None:
        self._lbl.setText(text)
        self.adjustSize()
        place_window(self, phys_x, phys_y, offset=(12, 12))
        self.show()
        self._timer.start(ms)


# ---------------------------------------------------------------- 弹窗


class DragHandle(QLabel):
    """只在标题区域拖动窗口，不影响译文选字、按钮或追问输入。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__("划译 · 拖动这里移动窗口", parent)
        self.setObjectName("statusLabel")
        self.setCursor(Qt.SizeAllCursor)
        self.setMinimumHeight(22)
        self._press_global = None
        self._window_start = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._window_start = self.window().pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            self.window().move(self._window_start + delta)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._press_global is not None:
            self._press_global = None
            self._window_start = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class QuestionInput(QPlainTextEdit):
    """多行追问输入：Enter 发送，Shift/Alt + Enter 换行。"""

    submitted = Signal()
    MAX_LENGTH = 2000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._composing = False
        self.setTabChangesFocus(True)
        self.setMinimumHeight(74)
        self.setMaximumHeight(110)
        self.textChanged.connect(self._limit_length)

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self._composing:
            modifiers = event.modifiers() & (Qt.ShiftModifier | Qt.AltModifier |
                                             Qt.ControlModifier | Qt.MetaModifier)
            if modifiers & (Qt.ShiftModifier | Qt.AltModifier):
                self.insertPlainText("\n")
                event.accept()
                return
            if modifiers == Qt.NoModifier:
                self.submitted.emit()
                event.accept()
                return
        super().keyPressEvent(event)

    def _limit_length(self) -> None:
        text = self.toPlainText()
        if len(text) <= self.MAX_LENGTH:
            return
        # Qt 文本游标使用 UTF-16 位置，不能直接用 Python 字符数切 emoji。
        limit = len(text[:self.MAX_LENGTH].encode("utf-16-le")) // 2
        cursor = self.textCursor()
        position = cursor.position()
        trim = QTextCursor(self.document())
        trim.setPosition(limit)
        trim.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        trim.removeSelectedText()
        cursor.setPosition(min(position, limit))
        self.setTextCursor(cursor)


class PopupWindow(QWidget):
    """译文、解释、追问弹窗，支持保持在最前与流式渲染。"""

    KINDS = ("translate", "explain", "chat")
    TAB_TITLES = {"translate": "译文", "explain": "解释", "chat": "追问"}

    switch_requested = Signal(str)  # 首次切到某标签需要发起请求
    retry_requested = Signal(str)
    stop_requested = Signal(str)
    close_requested = Signal()
    question_submitted = Signal(str)

    def __init__(self, cfg: dict) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 展示不抢焦点；用户点击窗口后可主动输入追问。

        popup = cfg.get("popup", {}) or {}
        self.resize(int(popup.get("width", 460)), int(popup.get("height", 320)))
        self.setMinimumSize(420, 320)
        self._max_text_len = int(cfg.get("max_text_len", 3000))

        self._source_text = ""
        self._truncated = False
        self._texts = {k: "" for k in self.KINDS}    # 已进入界面的文本
        self._bufs: dict[str, list] = {k: [] for k in self.KINDS}  # 待刷新增量
        self._labels: dict[str, QLabel] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        self._statuses: dict[str, QLabel] = {}
        self._retries: dict[str, QPushButton] = {}
        self._stops: dict[str, QPushButton] = {}
        self._pending: set[str] = set()
        self._t0: dict[str, float] = {}
        self._requested: set[str] = set()
        self._collapsed = True
        self._pinned = False
        self._chat_busy = False
        self._chat_turns: list[list[str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        frame = QWidget()
        frame.setObjectName("popupRoot")
        root.addWidget(frame)

        fv = QVBoxLayout(frame)
        fv.setContentsMargins(10, 8, 10, 8)
        fv.setSpacing(6)

        # —— 头部：原文 + 按钮
        head = QVBoxLayout()
        head.setSpacing(4)
        self.drag_handle = DragHandle(self)
        head.addWidget(self.drag_handle)
        self.lbl_source = QLabel("")
        self.lbl_source.setObjectName("sourceText")
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setTextFormat(Qt.PlainText)
        self.lbl_source.setTextInteractionFlags(Qt.NoTextInteraction)
        head.addWidget(self.lbl_source)

        hrow = QHBoxLayout()
        hrow.setSpacing(6)
        self.btn_expand = QToolButton()
        self.btn_expand.setVisible(False)
        self.btn_expand.clicked.connect(self._toggle_expand)
        hrow.addWidget(self.btn_expand)
        hrow.addStretch(1)
        self.lbl_trunc = QLabel("")
        self.lbl_trunc.setObjectName("truncBanner")
        self.lbl_trunc.setVisible(False)
        hrow.addWidget(self.lbl_trunc)
        self.btn_copy_src = QToolButton()
        self.btn_copy_src.setText("复制原文")
        self.btn_copy_src.clicked.connect(self._copy_source)
        hrow.addWidget(self.btn_copy_src)
        self.btn_pin = QToolButton()
        self.btn_pin.setText("显示在最前")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("保持结果窗口；点击其他应用和按 Esc 都不会关闭，点击 × 关闭。")
        self.btn_pin.toggled.connect(self._set_pinned)
        hrow.addWidget(self.btn_pin)
        self.btn_close = QToolButton()
        self.btn_close.setText("\u2715")
        self.btn_close.clicked.connect(self.close_requested.emit)
        hrow.addWidget(self.btn_close)
        head.addLayout(hrow)
        fv.addLayout(head)

        # —— 标签页
        self.tabs = QTabWidget()
        tabs_holder = self.tabs
        for i, kind in enumerate(self.KINDS):
            page = self._make_chat_page() if kind == "chat" else self._make_page(kind)
            tabs_holder.addTab(page, self.TAB_TITLES[kind])
        tabs_holder.currentChanged.connect(self._on_tab_changed)
        fv.addWidget(tabs_holder, 1)

        resize_row = QHBoxLayout()
        resize_hint = QLabel("拖动右下角调整大小")
        resize_hint.setObjectName("statusLabel")
        resize_row.addWidget(resize_hint)
        resize_row.addStretch(1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(20, 20)
        self.size_grip.setToolTip("按住右下角，拖动调整窗口大小。")
        resize_row.addWidget(self.size_grip, 0, Qt.AlignRight | Qt.AlignBottom)
        fv.addLayout(resize_row)

        # —— 流式渲染：30ms 批量刷新
        self._flush_timer = QTimer(self, interval=30, timeout=self._flush)
        self._flush_timer.start()

    def _make_page(self, kind: str) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 6)
        v.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QLabel("")
        content.setWordWrap(True)
        content.setTextFormat(Qt.PlainText)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(content)
        self._scrolls[kind] = scroll
        self._labels[kind] = content
        v.addWidget(scroll, 1)

        prow = QHBoxLayout()
        prow.setSpacing(6)
        status = QLabel("")
        status.setObjectName("statusLabel")
        prow.addWidget(status, 1)
        prow.addWidget(self._make_stop_button(kind))
        retry = QPushButton("重试")
        retry.setObjectName("retryBtn")
        retry.setVisible(False)
        retry.clicked.connect(lambda _=False: self.retry_requested.emit(kind))
        prow.addWidget(retry)
        self._statuses[kind] = status
        self._retries[kind] = retry
        v.addLayout(prow)

        brow = QHBoxLayout()
        brow.setSpacing(6)
        copy_btn = QPushButton("复制内容")
        copy_btn.clicked.connect(lambda _=False, k=kind: self._copy_page(k))
        brow.addWidget(copy_btn)
        brow.addStretch(1)
        v.addLayout(brow)
        return page

    def _make_chat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 6)
        self.chat_view = QPlainTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setPlaceholderText("可以继续问：为什么这样翻译？能举个例子吗？\n追问会结合原文、译文和解释。")
        self._scrolls["chat"] = self.chat_view
        layout.addWidget(self.chat_view, 1)
        status_row = QHBoxLayout()
        status = QLabel("")
        status.setObjectName("statusLabel")
        status_row.addWidget(status, 1)
        self._statuses["chat"] = status
        status_row.addWidget(self._make_stop_button("chat"))
        retry = QPushButton("重试")
        retry.setVisible(False)
        retry.clicked.connect(lambda: self.retry_requested.emit("chat"))
        self._retries["chat"] = retry
        status_row.addWidget(retry)
        layout.addLayout(status_row)
        input_row = QHBoxLayout()
        self.question_input = QuestionInput()
        self.question_input.setPlaceholderText("接着问…\nEnter 发送；Shift+Enter / Alt+Enter 换行")
        self.question_input.setToolTip("最多 2000 字符；Enter 发送，Shift+Enter 或 Alt+Enter 换行。")
        self.question_input.submitted.connect(self._submit_question)
        input_row.addWidget(self.question_input, 1)
        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self._submit_question)
        input_row.addWidget(self.btn_send, 0, Qt.AlignBottom)
        layout.addLayout(input_row)
        copy = QPushButton("复制对话")
        copy.clicked.connect(lambda: self._copy_page("chat"))
        layout.addWidget(copy)
        return page

    def _make_stop_button(self, kind: str) -> QPushButton:
        button = QPushButton("停止")
        button.setToolTip("终止本次生成，保留已经显示的内容。")
        button.setVisible(False)
        button.clicked.connect(lambda _=False: self.stop_requested.emit(kind))
        self._stops[kind] = button
        return button

    def is_pending(self, kind: str) -> bool:
        return kind in self._pending

    def _set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self.btn_pin.setText("已置顶" if pinned else "显示在最前")

    def is_pinned(self) -> bool:
        return self._pinned

    def _submit_question(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question or self._chat_busy:
            return
        self.question_input.clear()
        self.question_submitted.emit(question)

    def begin_question(self, question: str, retry: bool = False) -> None:
        self.btn_pin.setChecked(True)
        self._texts["chat"] = ""
        self._bufs["chat"].clear()
        if not retry or not self._chat_turns:
            self._chat_turns.append([question, ""])
        else:
            self._chat_turns[-1][1] = ""
        self._render_chat()
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def _render_chat(self) -> None:
        self.chat_view.setPlainText("\n\n".join(
            f"你：{question}\n\n划译：{answer}" for question, answer in self._chat_turns
        ))

    def result_text(self, kind: str) -> str:
        self._flush()
        return self._texts.get(kind, "")

    def reset_result(self, kind: str) -> None:
        self._texts[kind] = ""
        self._bufs[kind].clear()
        if kind != "chat":
            self._labels[kind].clear()

    # —— 对外 API（app 调用 / llm 信号接入）

    def open_at(self, phys_x: float, phys_y: float, text: str, truncated: bool,
                initial_kind: str) -> None:
        """弹窗在物理坐标 (phys_x, phys_y) 处出现（图标下方偏左 12px 由调用方算好）。"""
        self._source_text = text
        self._truncated = truncated
        self._texts = {k: "" for k in self.KINDS}
        self._bufs = {k: [] for k in self.KINDS}
        self._requested = {initial_kind}
        self._pending = {initial_kind}
        self._t0.clear()
        self._collapsed = True
        self._chat_turns.clear()
        self._chat_busy = False
        self.btn_send.setEnabled(True)
        self.question_input.clear()
        self.chat_view.clear()

        self.lbl_source.setText(text)
        self.lbl_source.setMaximumHeight(16777215)
        self._apply_collapse()
        self.lbl_trunc.setText(f"原文超长，已截断至 {self._max_text_len} 字符")
        self.lbl_trunc.setVisible(truncated)

        for k in self.KINDS:
            if k != "chat":
                self._labels[k].setText("")
            self._statuses[k].setText("请求中…" if k == initial_kind else "")
            self._statuses[k].setStyleSheet("")
            self._retries[k].setVisible(False)
            self._stops[k].setVisible(k == initial_kind)
            self._scrolls[k].verticalScrollBar().setValue(0)
        self.btn_expand.setText("\u25be 展开")

        idx = self.KINDS.index(initial_kind) if initial_kind in self.KINDS else 0
        if self.tabs.currentIndex() != idx:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(idx)
            self.tabs.blockSignals(False)

        place_window(self, phys_x, phys_y)
        self.show()

    def mark_pending(self, kind: str, t0: float | None = None) -> None:
        """请求已派发：状态置"请求中…"。"""
        self._statuses[kind].setText("请求中…")
        self._statuses[kind].setStyleSheet("")
        self._retries[kind].setVisible(False)
        self._retries[kind].setText("重试")
        self._pending.add(kind)
        self._stops[kind].setVisible(True)
        self._requested.add(kind)
        if kind == "chat":
            self._chat_busy = True
            self.btn_send.setEnabled(False)
        if t0 is not None:
            self._t0[kind] = t0

    def append_chunk(self, kind: str, delta: str) -> None:
        self._bufs.get(kind, []).append(delta)

    def mark_done(self, kind: str) -> None:
        self._flush()
        self._pending.discard(kind)
        self._stops[kind].setVisible(False)
        if kind == "chat":
            self._chat_busy = False
            self.btn_send.setEnabled(True)
        t0 = self._t0.get(kind)
        if t0 is not None:
            self._statuses[kind].setText(f"完成（{time.perf_counter() - t0:.1f}s）")
        else:
            self._statuses[kind].setText("完成")

    def mark_failed(self, kind: str, msg: str) -> None:
        self._pending.discard(kind)
        self._stops[kind].setVisible(False)
        if kind == "chat":
            self._chat_busy = False
            self.btn_send.setEnabled(True)
        self._statuses[kind].setText(msg)
        self._statuses[kind].setStyleSheet("color:#ff8a80;")
        self._retries[kind].setVisible(True)
        self._flush()

    def mark_stopped(self, kind: str) -> None:
        self._flush()
        self._pending.discard(kind)
        self._t0.pop(kind, None)
        self._stops[kind].setVisible(False)
        self._statuses[kind].setText("已停止（保留已生成内容）")
        self._statuses[kind].setStyleSheet("")
        self._retries[kind].setText("重新生成")
        self._retries[kind].setVisible(kind != "chat")
        if kind == "chat":
            self._chat_busy = False
            self.btn_send.setEnabled(True)
            if self.current_kind() == "chat":
                self.question_input.setFocus(Qt.OtherFocusReason)

    def current_kind(self) -> str:
        return self.KINDS[self.tabs.currentIndex()]

    def close_now(self) -> None:
        self._pending.clear()
        for button in self._stops.values():
            button.hide()
        self.hide()

    # —— 内部

    def _on_tab_changed(self, idx: int) -> None:
        kind = self.KINDS[idx]
        if kind == "chat":
            self.btn_pin.setChecked(True)
            self.resize(self.width(), max(self.height(), 460))
            self.activateWindow()
            self.question_input.setFocus(Qt.OtherFocusReason)
            return
        if kind not in self._requested:
            self._requested.add(kind)
            self.switch_requested.emit(kind)

    def _flush(self) -> None:
        for kind in self.KINDS:
            buf = self._bufs[kind]
            if not buf:
                continue
            scroll = self._scrolls[kind]
            bar = scroll.verticalScrollBar()
            previous_value = bar.value()
            stick = bar.maximum() == 0 or bar.value() >= bar.maximum() - 40
            self._texts[kind] += "".join(buf)
            buf.clear()
            if kind == "chat":
                if self._chat_turns:
                    self._chat_turns[-1][1] = self._texts[kind]
                self._render_chat()
            else:
                self._labels[kind].setText(self._texts[kind])
            if stick:
                bar.setValue(bar.maximum())
            else:
                bar.setValue(previous_value)

    def _apply_collapse(self) -> None:
        """原文 >3 行（约 >200 字符）时默认折叠，提供展开/收起。"""
        text = self._source_text
        need = len(text) > 200 or text.count("\n") > 2
        self.btn_expand.setVisible(need)
        fh = self.lbl_source.fontMetrics().height() * 3 + 6
        self.lbl_source.setMaximumHeight(fh if self._collapsed else 16777215)
        self.btn_expand.setText("\u25be 展开" if self._collapsed else "\u25b4 收起")

    def _toggle_expand(self) -> None:
        self._collapsed = not self._collapsed
        self._apply_collapse()

    def _copy_source(self) -> None:
        QApplication.clipboard().setText(self._source_text)

    def _copy_page(self, kind: str) -> None:
        self._flush()
        text = self.chat_view.toPlainText() if kind == "chat" else self._texts[kind]
        QApplication.clipboard().setText(text)


# ---------------------------------------------------------------- 托盘


class TrayIcon(QSystemTrayIcon):
    """托盘：退出 pythonw 进程的唯一入口。"""

    def __init__(self, actions: dict, parent=None) -> None:
        super().__init__(self._make_icon(), parent)
        self.setToolTip("划译 — 本地划词翻译")
        self.activated.connect(
            lambda reason: actions["show_status"]()
            if reason in (self.ActivationReason.Trigger, self.ActivationReason.DoubleClick)
            else None
        )

        menu = QMenu()
        menu.setStyleSheet(DARK_QSS)
        menu.addAction("状态与测试").triggered.connect(actions["show_status"])
        self.act_pause = menu.addAction("暂停监听")
        self.act_pause.triggered.connect(actions["pause"])
        menu.addAction("打开配置文件").triggered.connect(actions["open_config"])
        self.act_autostart = menu.addAction("开机自启动")
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(actions.get("autostart_enabled", False))
        self.act_autostart.toggled.connect(actions["set_autostart"])
        menu.addSeparator()
        menu.addAction("退出").triggered.connect(actions["exit"])
        self.setContextMenu(menu)

    def set_paused(self, paused: bool) -> None:
        self.act_pause.setText("恢复监听" if paused else "暂停监听")

    @staticmethod
    def _make_icon() -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#25292e"))
        p.drawRoundedRect(2, 2, 60, 60, 12, 12)
        p.setFont(QFont("Microsoft YaHei UI", 26, QFont.Bold))
        p.setPen(QColor("#7ec3ff"))
        p.drawText(pm.rect(), Qt.AlignCenter, "译")
        p.end()
        return QIcon(pm)


class StatusWindow(QWidget):
    """可见的启动入口；关闭窗口后继续在托盘运行。"""

    test_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("划译 — 本地划词翻译")
        self.setWindowIcon(TrayIcon._make_icon())
        self.setObjectName("popupRoot")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        title = QLabel("划译已启动")
        title.setStyleSheet("font-size:18pt;font-weight:bold;")
        layout.addWidget(title)
        self.listener_status = QLabel("监听已开启")
        layout.addWidget(self.listener_status)
        self.model_status = QLabel("正在连接并预热本地模型，首次可能需要约 30 秒…")
        self.model_status.setWordWrap(True)
        layout.addWidget(self.model_status)
        instructions = QLabel(
            "使用方法：\n"
            "在其他应用里选中文字，点击选区旁的「译」。\n"
            "也可以选中文字后按 Ctrl+Alt+Shift+T 翻译，或 Ctrl+Alt+Shift+E 解释。\n\n"
            "工具启动后安静地在后台运行。右键托盘图标可查看状态、设置开机自启动或退出。"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        layout.addWidget(QLabel("测试句：The battery stores energy."))
        buttons = QHBoxLayout()
        test = QPushButton("测试翻译")
        test.clicked.connect(self.test_requested.emit)
        buttons.addWidget(test)
        buttons.addStretch()
        background = QPushButton("后台运行")
        background.clicked.connect(self.hide)
        buttons.addWidget(background)
        exit_button = QPushButton("退出")
        exit_button.clicked.connect(self.quit_requested.emit)
        buttons.addWidget(exit_button)
        layout.addLayout(buttons)

    def show_status(self) -> None:
        # 无控制台快捷方式可能携带 SW_HIDE；重新显示可恢复原生窗口可见状态。
        self.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        log.info("打开划译启动窗口")

    def set_model_status(self, ok: bool, message: str) -> None:
        self.model_status.setText(message)
        self.model_status.setStyleSheet("color:#8ecbf5;" if ok else "color:#ff8a80;")

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()
