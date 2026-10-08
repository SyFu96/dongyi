"""启动窗口与单实例回归测试：uv run python -m unittest test_startup -v。"""

from pathlib import Path
import unittest

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from instance import SingleInstance
from popup import StatusWindow


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_second_launch_activates_first_and_does_not_own_server(self):
        path = Path(__file__).parent / "test-instance"
        first = SingleInstance(path)
        second = SingleInstance(path)
        try:
            self.assertTrue(first.acquire())
            activated = QSignalSpy(first.activated)
            self.assertFalse(second.acquire())
            QTest.qWait(100)
            self.assertEqual(activated.count(), 1)
            self.assertTrue(first.server.isListening())
            self.assertFalse(second.server.isListening())
            first.close()
            self.assertTrue(second.acquire())
        finally:
            first.close()
            second.close()

    def test_status_window_can_be_opened_on_demand_and_closed_to_background(self):
        window = StatusWindow()
        try:
            window.show_status()
            QTest.qWait(30)
            self.assertTrue(window.isVisible())
            window.close()
            self.assertFalse(window.isVisible())
            window.show_status()
            self.assertTrue(window.isVisible())
        finally:
            window.hide()
            window.deleteLater()

    def test_demo_and_exit_buttons_and_model_feedback(self):
        window = StatusWindow()
        try:
            demo = QSignalSpy(window.test_requested)
            quit_requested = QSignalSpy(window.quit_requested)
            buttons = {b.text(): b for b in window.findChildren(QPushButton)}
            buttons["测试翻译"].click()
            self.assertEqual(demo.count(), 1)
            buttons["退出"].click()
            self.assertEqual(quit_requested.count(), 1)
            window.set_model_status(False, "无法连接本地翻译服务")
            self.assertIn("无法连接", window.model_status.text())
            window.set_model_status(True, "本地模型已就绪")
            self.assertIn("已就绪", window.model_status.text())
        finally:
            window.hide()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
