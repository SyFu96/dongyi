"""外观偏好保存、实时切换与系统主题通知的回归检查。"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

import app as dongyi
from test_features import FakeLlm
from theme import app_theme_qss, resolve_theme, theme_color


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.old_qss = self.qt.styleSheet()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config_path = Path(folder.name) / "config.json"
        for guard in (
            patch.object(dongyi, "DATA_DIR", Path(folder.name)),
            patch.object(dongyi, "CONFIG_PATH", self.config_path),
            patch.object(dongyi.llm, "LlmClient", FakeLlm),
            patch.object(dongyi.startup, "is_enabled", return_value=False),
            patch.object(dongyi.SettingsWindow, "_refresh_local_models"),
        ):
            guard.start()
            self.addCleanup(guard.stop)
        cfg = deepcopy(dongyi.DEFAULTS)
        cfg["domains"] = {}
        self.controller = dongyi.App(cfg)
        self.controller.settings.reload()

    def tearDown(self):
        c = self.controller
        for window in (c.popup, c.icon, c.toast, c.status, c.settings):
            window.hide()
            window.deleteLater()
        c.tray.hide()
        c.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.qt.processEvents()
        self.qt.setStyleSheet(self.old_qss)

    def test_resolve_system_and_explicit_preferences(self):
        for scheme, expected in ((Qt.ColorScheme.Light, "light"),
                                 (Qt.ColorScheme.Dark, "dark"),
                                 (Qt.ColorScheme.Unknown, "dark")):
            self.assertEqual(resolve_theme("system", scheme), expected)
            for preference in ("dark", "light"):
                self.assertEqual(resolve_theme(preference, scheme), preference)

    def test_save_all_preferences_applies_and_persists(self):
        c = self.controller
        for preference in ("light", "dark", "system"):
            c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData(preference))
            c.settings._on_save()
            self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["theme"], preference)
            self.assertEqual(self.qt.styleSheet(), app_theme_qss(resolve_theme(preference)))
            c.settings.reload()
            self.assertEqual(c.settings.theme_combo.currentData(), preference)

    def test_cancel_does_not_change_preference(self):
        c = self.controller
        c._apply_theme()
        c.settings.show()
        c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData("light"))
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("light"))
        self.assertEqual(c._cfg["theme"], "dark")
        self.assertFalse(self.config_path.exists())
        c.settings.hide()
        c.settings.reload()
        self.assertEqual(c._cfg["theme"], "dark")
        self.assertEqual(c.settings.theme_combo.currentData(), "dark")
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("dark"))

    def test_titlebar_close_restores_saved_theme(self):
        c = self.controller
        c.settings.show()
        c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData("light"))
        c.settings.close()
        self.assertIsNone(c._theme_preview)
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("dark"))

    def test_system_preview_follows_signals_before_save(self):
        c = self.controller
        c.settings.show()
        c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData("system"))
        self.assertEqual(c._cfg["theme"], "dark")
        for scheme, theme in ((Qt.ColorScheme.Light, "light"), (Qt.ColorScheme.Dark, "dark")):
            self.qt.styleHints().colorSchemeChanged.emit(scheme)
            self.assertEqual(self.qt.styleSheet(), app_theme_qss(theme))
        c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData("light"))
        self.qt.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("light"))
        c.settings.hide()
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("dark"))

    def test_save_keeps_preview_when_settings_hides(self):
        c = self.controller
        c.settings.show()
        c.settings.theme_combo.setCurrentIndex(c.settings.theme_combo.findData("light"))
        c.settings._on_save()
        self.assertFalse(c.settings.isVisible())
        self.assertIsNone(c._theme_preview)
        self.assertEqual(c._cfg["theme"], "light")
        self.assertEqual(self.qt.styleSheet(), app_theme_qss("light"))

    def test_system_signal_updates_colors_and_preserves_content(self):
        c = self.controller
        c._cfg["theme"] = "system"
        c.popup.open_at(0, 0, "Source", False, "translate")
        c.popup.append_chunk("translate", "Partial result")
        c.popup.mark_failed("translate", "Connection failed")
        c.popup.question_input.setPlainText("Unsent draft")
        for scheme, theme in ((Qt.ColorScheme.Light, "light"), (Qt.ColorScheme.Dark, "dark")):
            # 发出真实 Qt 信号，不修改用户的 Windows 个性化设置。
            self.qt.styleHints().colorSchemeChanged.emit(scheme)
            self.qt.processEvents()
            self.assertEqual(self.qt.styleSheet(), app_theme_qss(theme))
            self.assertEqual(c.popup.size_grip._color.name(), theme_color(theme, "muted"))
            self.assertIn(theme_color(theme, "surface"), c.icon._lbl.styleSheet())
            self.assertIn(theme_color(theme, "text"), c.toast._lbl.styleSheet())
            self.assertEqual(c.popup._statuses["translate"].palette().color(QPalette.WindowText).name(),
                             theme_color(theme, "error"))
            self.assertEqual(c.popup.result_text("translate"), "Partial result")
            self.assertEqual(c.popup.question_input.toPlainText(), "Unsent draft")
            self.assertEqual(c._cfg["theme"], "system")
        c.popup.mark_pending("translate")
        self.assertEqual(c.popup._statuses["translate"].property("feedback"), "")

    def test_explicit_theme_ignores_system_signal(self):
        c = self.controller
        for theme, scheme in (("dark", Qt.ColorScheme.Light), ("light", Qt.ColorScheme.Dark)):
            c._cfg["theme"] = theme
            c._apply_theme()
            self.qt.styleHints().colorSchemeChanged.emit(scheme)
            self.assertEqual(self.qt.styleSheet(), app_theme_qss(theme))


if __name__ == "__main__":
    unittest.main()
