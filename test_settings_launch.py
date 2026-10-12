"""通过真实 SW_HIDE 子进程检查原生可见性，避免只断言 Qt 的 isVisible()。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


CHILD = r'''
from copy import deepcopy
import json
import sys
from unittest.mock import patch
import app as dongyi
import win32gui
from PySide6.QtWidgets import QApplication
from popup import StatusWindow, app_theme_qss
from settings import SettingsWindow

qt = QApplication([])
qt.setStyleSheet(app_theme_qss('dark'))
with patch.object(SettingsWindow, '_refresh_local_models'):
    if sys.argv[1] == 'settings':
        window = SettingsWindow(deepcopy(dongyi.DEFAULTS))
        show = window.open_window
    else:
        window = StatusWindow()
        show = window.show_status
    observations = []
    for state in ('first', 'hidden', 'minimized'):
        if state == 'hidden':
            window.hide()
        elif state == 'minimized':
            window.showMinimized()
        show()
        qt.processEvents()
        hwnd = int(window.winId())
        observations.append({'state': state, 'qt_visible': window.isVisible(),
                             'native_visible': bool(win32gui.IsWindowVisible(hwnd)),
                             'minimized': bool(win32gui.IsIconic(hwnd))})
    window.hide()
print(json.dumps(observations))
'''


@unittest.skipUnless(sys.platform == "win32", "验证 Windows 静默启动")
class SilentWindowTests(unittest.TestCase):
    def check_window(self, kind):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # 与 launch.vbs / 开机自启动的 SW_HIDE 一致。
        result = subprocess.run(
            [sys.executable, "-c", CHILD, kind],
            cwd=Path(__file__).resolve().parent,
            startupinfo=startup, capture_output=True, text=True, timeout=15,
            # 此测试必须用原生 Windows 后端，不能被 CI 的 offscreen 覆盖。
            env={**os.environ, "QT_QPA_PLATFORM": "windows"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in json.loads(result.stdout):
            with self.subTest(state=row["state"]):
                self.assertTrue(row["qt_visible"])
                self.assertTrue(row["native_visible"])
                self.assertFalse(row["minimized"])

    def test_settings_from_silent_startup(self):
        self.check_window("settings")

    def test_status_from_silent_startup(self):
        self.check_window("status")


if __name__ == "__main__":
    unittest.main()
