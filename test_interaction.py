"""热键误触发及结果窗口拖动的回归测试。"""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from pynput.keyboard import Key, KeyCode

import trigger
from popup import PopupWindow


class HotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.held = set()
        self.guard = patch.object(trigger, "_modifier_is_down", side_effect=lambda key: key in self.held, create=True)
        self.guard.start()
        self.monitor = trigger.Monitor({"hotkeys": {"translate": "<ctrl>+<alt>+t", "explain": "<ctrl>+<alt>+e"}})
        self.events = QSignalSpy(self.monitor.hotkey)
        self.listener = self.monitor._keys

    def tearDown(self):
        self.guard.stop()

    def press(self, key, injected=False):
        self.listener._on_press(key, injected)

    def release(self, key, injected=False):
        self.listener._on_release(key, injected)

    def test_plain_e_and_t_do_not_activate(self):
        for letter in ("e", "t", "E", "T"):
            key = KeyCode.from_char(letter)
            self.press(key)
            self.release(key)
        self.assertEqual(self.events.count(), 0)

    def test_missing_modifier_release_cannot_turn_e_into_hotkey(self):
        self.held = {Key.ctrl, Key.alt}
        self.press(Key.ctrl)
        self.press(Key.alt)
        e = KeyCode.from_char("e")
        self.press(e)
        self.release(e)
        self.assertEqual(self.events.count(), 1)
        self.assertEqual(self.events.at(0), ["explain"])
        # 模拟切换焦点/模拟 Ctrl+C 时遗漏了修饰键抬起回调。
        self.held.clear()
        self.press(e)
        self.release(e)
        self.assertEqual(self.events.count(), 1)
        # 清除残留状态后，真正的完整组合仍然正常。
        self.held = {Key.ctrl, Key.alt}
        self.press(Key.ctrl)
        self.press(Key.alt)
        self.press(e)
        self.assertEqual(self.events.count(), 2)

    def test_full_combo_once_per_press_and_injected_events_ignored(self):
        self.held = {Key.ctrl, Key.alt}
        self.press(Key.ctrl)
        self.press(Key.alt)
        t = KeyCode.from_char("t")
        self.press(t, injected=True)
        self.assertEqual(self.events.count(), 0)
        self.press(t)
        self.press(t)
        self.assertEqual(self.events.count(), 1)
        self.assertEqual(self.events.at(0), ["translate"])
        self.release(t)
        self.press(t)
        self.assertEqual(self.events.count(), 2)


class DragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def test_drag_moves_all_three_tabs_without_clearing_content(self):
        window = PopupWindow({})
        try:
            window.open_at(250, 200, "The battery stores energy.", False, "translate")
            window.append_chunk("translate", "电池储存能量。")
            window.mark_done("translate")
            for index in range(3):
                with self.subTest(tab=index):
                    window.tabs.setCurrentIndex(index)
                    QTest.qWait(10)
                    start = window.pos()
                    handle = window.drag_handle
                    local = QPoint(12, 10)
                    global_start = handle.mapToGlobal(local)
                    QTest.mousePress(handle, Qt.LeftButton, pos=local)
                    delta = QPoint(75, 42)
                    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(local + delta),
                                       QPointF(global_start + delta), Qt.NoButton,
                                       Qt.LeftButton, Qt.NoModifier)
                    QApplication.sendEvent(handle, move)
                    QTest.mouseRelease(handle, Qt.LeftButton, pos=local)
                    self.assertEqual(window.pos(), start + delta)
                    self.assertTrue(window.isVisible())
                    self.assertEqual(window.result_text("translate"), "电池储存能量。")
                    self.assertEqual(window.tabs.currentIndex(), index)
        finally:
            window.hide()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
