"""统一的深浅主题：颜色集中管理，弹窗与设置共用控件样式。"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

PALETTES = {
    "dark": dict(bg="#0d1422", surface="#131e30", field="#101a2a",
                 text="#e5edf8", muted="#8c9eb6", border="#25364c",
                 hover="#20334b", accent="#5cddf5", tint="#173c50",
                 primary="#12667e", primary_hover="#177f99", error="#ff8996"),
    "light": dict(bg="#f3f7fb", surface="#ffffff", field="#f7fafd",
                  text="#20334b", muted="#667b93", border="#dce5ef",
                  hover="#eaf2fa", accent="#087b99", tint="#e0f4fa",
                  primary="#087b99", primary_hover="#096780", error="#c53350"),
}


def resolve_theme(preference: str, scheme=None) -> str:
    """保留用户的 system 偏好，只将实际显示解析为深色或浅色。"""
    if preference in PALETTES:
        return preference
    if preference == "system":
        if scheme is None and QGuiApplication.instance():
            scheme = QGuiApplication.styleHints().colorScheme()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"
    return "dark"


def set_feedback(widget, state: str) -> None:
    """状态颜色由主题接管；刷新属性后立即重绘，不残留旧主题的内联颜色。"""
    widget.setProperty("feedback", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def theme_color(theme: str, role: str) -> str:
    return PALETTES[resolve_theme(theme)][role]


def app_theme_qss(theme: str) -> str:
    c = dict(PALETTES[resolve_theme(theme)])
    c["arrow"] = (Path(__file__).resolve().parent / "assets" / "chevron.png").as_posix()
    # 使用模板共用布局规则，避免深浅主题的尺寸和交互状态出现差异。
    return """
    * { font-family: "Microsoft YaHei UI"; font-size: 10pt; color: %(text)s; }
    QWidget { background: transparent; }
    QWidget#popupRoot, QWidget#settingsRoot, QDialog {
        background: %(bg)s; border: 1px solid %(border)s; border-radius: 12px;
    }
    QWidget#settingsBody { background: %(bg)s; }
    QLabel { background: transparent; border: none; }
    QLabel#brandTitle { color: %(text)s; font-size: 12pt; font-weight: 600; }
    QLabel#brandMark {
        color: %(accent)s; background: %(tint)s; border: 1px solid %(border)s;
        border-radius: 8px; font-size: 12pt; font-weight: 600;
    }
    QLabel#sectionLabel, QLabel#statusLabel { color: %(muted)s; font-size: 9pt; }
    QLabel[feedback="error"], QLabel#statusLabel[feedback="error"] { color: %(error)s; }
    QLabel[feedback="success"], QLabel#statusLabel[feedback="success"] { color: %(accent)s; }
    QLabel#sectionLabel { font-weight: 600; }
    QLabel#sourceText {
        color: %(muted)s; background: %(field)s; border: 1px solid %(border)s;
        border-radius: 8px; padding: 10px 12px;
    }
    QLabel#resultText { font-size: 11pt; padding: 4px 2px; }
    QLabel#truncBanner { color: #dca756; font-size: 9pt; }
    QTabWidget::pane {
        background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px;
        top: 8px;
    }
    QTabBar::tab {
        background: transparent; color: %(muted)s; border: none;
        border-bottom: 2px solid transparent; padding: 8px 13px; margin-right: 4px;
    }
    QTabBar::tab:selected { color: %(accent)s; border-bottom: 2px solid %(accent)s; }
    QTabBar::tab:hover { color: %(text)s; background: %(hover)s; }
    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical { width: 6px; background: transparent; margin: 2px 0; }
    QScrollBar::handle:vertical { background: %(border)s; border-radius: 3px; min-height: 24px; }
    QScrollBar::handle:vertical:hover { background: %(muted)s; }
    QScrollBar:horizontal { height: 6px; background: transparent; }
    QScrollBar::handle:horizontal { background: %(border)s; border-radius: 3px; min-width: 24px; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
    QPushButton, QToolButton {
        background: %(field)s; border: 1px solid %(border)s; border-radius: 7px;
        padding: 5px 12px; min-height: 18px;
    }
    QPushButton:hover, QToolButton:hover { background: %(hover)s; border-color: %(muted)s; }
    QPushButton:pressed, QToolButton:pressed { background: %(tint)s; }
    QPushButton:disabled, QToolButton:disabled { color: %(muted)s; }
    QPushButton:focus, QToolButton:focus { border-color: %(accent)s; }
    QPushButton#primaryBtn {
        background: %(primary)s; color: #ffffff; border-color: %(primary)s; font-weight: 600;
    }
    QPushButton#primaryBtn:hover { background: %(primary_hover)s; border-color: %(primary_hover)s; }
    QPushButton#primaryBtn:disabled { background: %(border)s; color: %(muted)s; }
    QToolButton#headerBtn { background: transparent; border-color: transparent; padding: 3px 8px; }
    QToolButton#headerBtn:hover { background: %(hover)s; }
    QToolButton:checked, QToolButton#headerBtn:checked { background: %(tint)s; color: %(accent)s; }
    QToolButton#closeBtn { background: transparent; border: none; padding: 3px; font-size: 13pt; }
    QToolButton#closeBtn:hover { background: #783342; color: #ffffff; }
    QPushButton#retryBtn { color: %(accent)s; }
    QLineEdit, QPlainTextEdit, QListWidget {
        background: %(field)s; border: 1px solid %(border)s; border-radius: 7px;
        padding: 7px; selection-background-color: %(primary)s; selection-color: #ffffff;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus { border-color: %(accent)s; }
    QPlainTextEdit#chatView { background: transparent; border: none; padding: 2px; }
    QComboBox {
        background: %(field)s; border: 1px solid %(border)s; border-radius: 7px;
        padding: 5px 10px; min-height: 18px;
    }
    QComboBox:focus { border-color: %(accent)s; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox::down-arrow { image: url("%(arrow)s"); width: 12px; height: 8px; }
    QComboBox QAbstractItemView {
        background: %(surface)s; color: %(text)s; border: 1px solid %(border)s;
        selection-background-color: %(tint)s; selection-color: %(accent)s; padding: 4px;
    }
    QGroupBox {
        background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px;
        margin-top: 14px; padding: 18px 14px 12px;
    }
    QGroupBox::title {
        subcontrol-origin: margin; subcontrol-position: top left;
        left: 16px; padding: 0 6px; color: %(accent)s; font-weight: 600;
    }
    QCheckBox, QRadioButton { spacing: 8px; padding: 3px 0; }
    QCheckBox::indicator, QRadioButton::indicator {
        width: 15px; height: 15px; border: 1px solid %(muted)s; background: %(field)s;
    }
    QCheckBox::indicator { border-radius: 4px; }
    QRadioButton::indicator { border-radius: 8px; }
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {
        background: %(accent)s; border: 4px solid %(tint)s;
    }
    QMenu { background: %(surface)s; border: 1px solid %(border)s; padding: 5px; }
    QMenu::item { padding: 7px 24px; border-radius: 4px; }
    QMenu::item:selected { background: %(hover)s; color: %(accent)s; }
    QMenu::separator { height: 1px; background: %(border)s; margin: 5px 10px; }
    QToolTip { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 6px; }
    """ % c
