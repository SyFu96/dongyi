"""静默启动、保留结果、连续追问与取消请求的回归检查。"""

from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as huayi
import llm
from capture import Selection


class FakeLlm(QObject):
    chunk = Signal(str, str)
    finished = Signal(str, str)
    failed = Signal(str, str)
    warmup_finished = Signal(bool, str)

    def __init__(self, cfg, parent):
        super().__init__(parent)
        self.requests = []
        self.cancellations = []

    def request(self, kind, text, messages=None):
        self.requests.append((kind, text, deepcopy(messages)))

    def cancel(self, *kinds):
        self.cancellations.append(kinds)

    def preheat(self):
        pass

    def close(self):
        pass


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch.object(huayi.llm, "LlmClient", FakeLlm), patch.object(huayi.startup, "is_enabled", return_value=False):
            self.controller = huayi.App(deepcopy(huayi.DEFAULTS))

    def tearDown(self):
        c = self.controller
        c._startup_retry.stop()
        c._keepalive.stop()
        c._debounce.stop()
        for window in (c.popup, c.icon, c.toast, c.status):
            window.hide()
            window.deleteLater()
        c.tray.hide()
        c.deleteLater()
        QTest.qWait(5)

    def open_selection(self, text="The battery stores energy."):
        c = self.controller
        c._sel = Selection(text=text)
        c._icon_anchor = (100, 100)
        c._open_popup("translate")
        QTest.qWait(5)

    def test_normal_start_has_no_status_window(self):
        c = self.controller
        with patch.object(c.worker, "start"), patch.object(c.monitor, "start"), patch.object(c, "_startup"):
            c.start()
            QTest.qWait(5)
        self.assertFalse(c.status.isVisible())
        self.assertFalse(c.popup.isVisible())
        self.assertTrue(c.tray.isVisible())

    def test_pin_retains_result_after_external_click_escape_and_selection(self):
        c = self.controller
        self.open_selection()
        c.popup.btn_pin.click()
        self.assertTrue(c.popup.windowFlags() & Qt.WindowStaysOnTopHint)
        c.on_mouse_down({"phys": (-5000, -5000)})
        c.on_esc()
        c.on_captured({"req": {"purpose": "icon"}, "sel": Selection(text="Another selection")})
        self.assertTrue(c.popup.isVisible())
        self.assertEqual(c._sel.text, "The battery stores energy.")
        c.popup.btn_pin.click()
        c.on_mouse_down({"phys": (-5000, -5000)})
        self.assertFalse(c.popup.isVisible())

    def test_question_receives_original_results_and_previous_turns(self):
        c = self.controller
        self.open_selection()
        c.popup.append_chunk("translate", "电池储存能量。")
        c.popup.append_chunk("explain", "电池将能量储存在化学物质中。")
        c.popup.tabs.setCurrentIndex(2)
        self.assertTrue(c.popup.is_pinned())
        self.assertFalse(c.popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        c.popup.question_input.setText("stores 是什么意思？")
        QTest.keyClick(c.popup.question_input, Qt.Key_Return)
        kind, question, messages = c.llm.requests[-1]
        self.assertEqual(kind, "chat")
        self.assertIn("The battery stores energy.", messages[0]["content"])
        self.assertIn("电池储存能量。", messages[0]["content"])
        self.assertIn("化学物质", messages[0]["content"])
        c.llm.chunk.emit("chat", "stores 表示储存。")
        c.llm.finished.emit("chat", "stores 表示储存。")
        c.popup.question_input.setText("换个例子。")
        c.popup.btn_send.click()
        messages = c.llm.requests[-1][2]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[2]["content"], "stores 表示储存。")
        self.assertIn("stores 表示储存。", c.popup.chat_view.toPlainText())

    def test_failed_question_retry_does_not_duplicate_history_and_new_text_clears_it(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.on_question("请解释。")
        c.llm.failed.emit("chat", "临时连接错误")
        self.assertTrue(c.popup.btn_send.isEnabled())
        self.assertEqual(c._chat_history, [])
        c.popup._retries["chat"].click()
        self.assertEqual(len(c.popup._chat_turns), 1)
        c.llm.chunk.emit("chat", "这是解释。")
        c.llm.finished.emit("chat", "这是解释。")
        self.assertEqual(len(c._chat_history), 2)
        self.open_selection("A new text.")
        self.assertEqual(c._chat_history, [])
        self.assertEqual(c.popup.chat_view.toPlainText(), "")
        self.assertIn("chat", c.llm.cancellations[-2])

    def test_ollama_late_start_retries_without_opening_window(self):
        c = self.controller
        with patch.object(c, "_start_local_ollama"):
            c._on_ollama_checked(False)
        self.assertTrue(c._startup_retry.isActive())
        self.assertFalse(c.status.isVisible())
        c._on_ollama_checked(True)
        self.assertFalse(c._startup_retry.isActive())


class RequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_new_requests_work_without_preheat_and_cancelled_results_are_not_delivered(self):
        started, release = threading.Event(), threading.Event()
        completed, chunks = [], []

        def fake_stream(cfg, kind, text, on_chunk=None, **kwargs):
            if text == "old":
                started.set()
                release.wait(2)
            on_chunk(text)
            return text

        with patch.object(llm, "stream_chat", fake_stream):
            client = llm.LlmClient({})
            client.chunk.connect(lambda kind, delta: chunks.append(delta))
            client.finished.connect(lambda kind, text: completed.append(text))
            try:
                client.request("chat", "old", messages=[{"role": "user", "content": "old"}])
                self.assertTrue(started.wait(1))
                old_id = client._current_id("chat")
                client._delivery.emit("chunk", old_id, "chat", "queued old chunk")
                client.request("chat", "new")
                release.set()
                for _ in range(100):
                    QTest.qWait(10)
                    if completed:
                        break
                self.assertEqual(completed, ["new"])
                self.assertEqual(chunks, ["new"])
                self.assertGreater(client._current_id("chat"), old_id)
            finally:
                release.set()
                client.close()
                for worker in client._workers.values():
                    worker.join(1)
                client.deleteLater()


if __name__ == "__main__":
    unittest.main()
