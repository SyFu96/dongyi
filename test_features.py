"""静默启动、保留结果、连续追问与取消请求的回归检查。"""

from copy import deepcopy
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QInputMethodEvent
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
        self.assertTrue(c.icon.isVisible())
        self.assertEqual(c._icon_sel.text, "Another selection")
        c.popup.btn_pin.click()
        c.on_mouse_down({"phys": (-5000, -5000)})
        self.assertFalse(c.popup.isVisible())

    def test_pinned_window_does_not_block_drag_capture(self):
        c = self.controller
        self.open_selection()
        c.popup.btn_pin.setChecked(True)
        with patch.object(c.worker, "submit") as submit:
            c.on_attempt({"phys": (-5000, -5000), "action": "drag"})
            self.assertTrue(c._debounce.isActive())
            c._debounce.stop()
            c._fire_debounced()
            submit.assert_called_once_with("silent", "icon", (-5000, -5000), 3000)
        self.assertTrue(c.popup.isVisible())

    def test_first_selection_icon_opens_popup_without_existing_source(self):
        c = self.controller
        self.assertIsNone(c._sel)
        c.on_captured({"req": {"purpose": "icon", "phys": (200, 200)},
                       "sel": Selection(text="First selection.")})
        self.assertTrue(c.icon.isVisible())
        QTest.mouseClick(c.icon, Qt.LeftButton, pos=c.icon.rect().center())
        self.assertTrue(c.popup.isVisible())
        self.assertEqual(c._sel.text, "First selection.")
        self.assertEqual(c.llm.requests[-1][:2], ("translate", "First selection."))

    def test_new_selection_icon_on_every_tab_only_switches_text_after_click(self):
        c = self.controller
        for index in range(3):
            with self.subTest(tab=index):
                self.open_selection()
                c.popup.tabs.setCurrentIndex(index)
                c.popup.btn_pin.setChecked(True)
                c.popup.append_chunk("translate", "电池储存能量。")
                c._chat_history = [{"role": "user", "content": "旧问题"},
                                   {"role": "assistant", "content": "旧回答"}]
                prior_requests = len(c.llm.requests)
                prior_cancels = len(c.llm.cancellations)
                c.on_captured({"req": {"purpose": "icon", "phys": (-5000, -5000)},
                               "sel": Selection(text="A new text.")})
                self.assertTrue(c.icon.isVisible())
                self.assertTrue(c.popup.isVisible())
                self.assertEqual(c._sel.text, "The battery stores energy.")
                self.assertEqual(c.popup._source_text, c._sel.text)
                self.assertEqual(c.popup.result_text("translate"), "电池储存能量。")
                self.assertEqual(len(c._chat_history), 2)
                self.assertEqual(len(c.llm.requests), prior_requests)
                self.assertEqual(len(c.llm.cancellations), prior_cancels)
                c.icon.clicked.emit()
                self.assertEqual(c._sel.text, "A new text.")
                self.assertEqual(c.popup._source_text, "A new text.")
                self.assertEqual(c._chat_history, [])
                self.assertEqual(c.llm.requests[-1][:2], ("translate", "A new text."))
                self.assertIsNone(c._icon_sel)
                self.assertFalse(c.icon.isVisible())

    def test_candidate_selection_does_not_pollute_old_question_context(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.on_captured({"req": {"purpose": "icon", "phys": (-5000, -5000)},
                       "sel": Selection(text="A different source.")})
        c.on_question("解释原文。")
        context = c.llm.requests[-1][2][0]["content"]
        self.assertIn("The battery stores energy.", context)
        self.assertNotIn("A different source.", context)

    def test_dragging_own_ui_and_empty_selection_still_do_not_show_icon(self):
        c = self.controller
        self.open_selection()
        c.popup.btn_pin.setChecked(True)
        with patch.object(c, "_inside_own_ui", return_value=True), patch.object(c.worker, "submit") as submit:
            c.on_attempt({"phys": (100, 100), "action": "drag"})
            c._fire_debounced()
            submit.assert_not_called()
        c.on_captured({"req": {"purpose": "icon"}, "sel": Selection(text="candidate")})
        c.on_captured({"req": {"purpose": "icon"}, "sel": None})
        self.assertFalse(c.icon.isVisible())
        self.assertIsNone(c._icon_sel)
        self.assertEqual(c._sel.text, "The battery stores energy.")

    def test_question_receives_original_results_and_previous_turns(self):
        c = self.controller
        self.open_selection()
        c.popup.append_chunk("translate", "电池储存能量。")
        c.popup.append_chunk("explain", "电池将能量储存在化学物质中。")
        c.popup.tabs.setCurrentIndex(2)
        self.assertTrue(c.popup.is_pinned())
        self.assertFalse(c.popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        c.popup.question_input.setPlainText("stores 是什么意思？")
        QTest.keyClick(c.popup.question_input, Qt.Key_Return)
        kind, question, messages = c.llm.requests[-1]
        self.assertEqual(kind, "chat")
        self.assertIn("The battery stores energy.", messages[0]["content"])
        self.assertIn("电池储存能量。", messages[0]["content"])
        self.assertIn("化学物质", messages[0]["content"])
        c.llm.chunk.emit("chat", "stores 表示储存。")
        c.llm.finished.emit("chat", "stores 表示储存。")
        c.popup.question_input.setPlainText("换个例子。")
        c.popup.btn_send.click()
        messages = c.llm.requests[-1][2]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[2]["content"], "stores 表示储存。")
        self.assertIn("stores 表示储存。", c.popup.chat_view.toPlainText())

    def test_shift_and_alt_enter_insert_newline_without_sending(self):
        c = self.controller
        for key in (Qt.Key_Return, Qt.Key_Enter):
            for modifier in (Qt.ShiftModifier, Qt.AltModifier):
                with self.subTest(key=key, modifier=modifier):
                    self.open_selection()
                    c.popup.tabs.setCurrentIndex(2)
                    editor = c.popup.question_input
                    requests = len(c.llm.requests)
                    editor.insertPlainText("第一行问题")
                    QTest.keyClick(editor, key, modifier)
                    self.assertEqual(editor.toPlainText(), "第一行问题\n")
                    self.assertEqual(len(c.llm.requests), requests)
                    editor.insertPlainText("第二行补充")
                    QTest.keyClick(editor, key)
                    expected = "第一行问题\n第二行补充"
                    self.assertEqual(len(c.llm.requests), requests + 1)
                    self.assertEqual(c.llm.requests[-1][1], expected)
                    self.assertEqual(c.llm.requests[-1][2][-1]["content"], expected)
                    self.assertEqual(c.popup._chat_turns[-1][0], expected)
                    self.assertEqual(editor.toPlainText(), "")

    def test_send_button_preserves_multiline_text_and_blank_lines(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.popup.question_input.setPlainText("第一段。\n\n第二段，包含补充说明。")
        c.popup.btn_send.click()
        self.assertEqual(c.llm.requests[-1][1], "第一段。\n\n第二段，包含补充说明。")
        self.assertEqual(c.popup.question_input.toPlainText(), "")

    def test_multiline_draft_is_retained_while_busy_and_sendable_after_stop(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.on_question("正在回答的问题。")
        editor = c.popup.question_input
        editor.insertPlainText("下一问第一行")
        QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
        editor.insertPlainText("下一问第二行")
        requests = len(c.llm.requests)
        QTest.keyClick(editor, Qt.Key_Return)
        self.assertEqual(len(c.llm.requests), requests)
        self.assertEqual(editor.toPlainText(), "下一问第一行\n下一问第二行")
        c.popup._stops["chat"].click()
        QTest.keyClick(editor, Qt.Key_Return)
        self.assertEqual(c.llm.requests[-1][1], "下一问第一行\n下一问第二行")

    def test_ime_composition_enter_does_not_submit_question(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        editor = c.popup.question_input
        editor.insertPlainText("问题：")
        requests = len(c.llm.requests)
        QApplication.sendEvent(editor, QInputMethodEvent("pin", []))
        QTest.keyClick(editor, Qt.Key_Return)
        self.assertEqual(len(c.llm.requests), requests)
        committed = QInputMethodEvent("", [])
        committed.setCommitString("拼音")
        QApplication.sendEvent(editor, committed)
        self.assertIn("拼音", editor.toPlainText())
        QTest.keyClick(editor, Qt.Key_Return)
        self.assertEqual(len(c.llm.requests), requests + 1)

    def test_multiline_input_keeps_length_limit_without_splitting_emoji(self):
        c = self.controller
        editor = c.popup.question_input
        text = "第一行\n" + "😀" * 2100
        editor.setPlainText(text)
        self.assertEqual(editor.toPlainText(), text[:2000])
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        editor.insertPlainText("超出长度")
        self.assertEqual(editor.toPlainText(), text[:2000])

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

    def test_stop_explanation_keeps_buffer_and_can_regenerate(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(1)
        self.assertTrue(c.popup._stops["explain"].isVisible())
        c.llm.chunk.emit("explain", "已经解释的部分。")
        c.popup._stops["explain"].click()
        self.assertEqual(c.llm.cancellations[-1], ("explain",))
        self.assertEqual(c.popup.result_text("explain"), "已经解释的部分。")
        self.assertFalse(c.popup.is_pending("explain"))
        self.assertTrue(c.popup.is_pending("translate"))
        self.assertFalse(c.popup._stops["explain"].isVisible())
        self.assertTrue(c.popup._statuses["explain"].text().startswith("已停止"))
        c.popup._retries["explain"].click()
        self.assertTrue(c.popup.is_pending("explain"))
        self.assertEqual(c.popup.result_text("explain"), "")
        self.assertEqual(c.llm.requests[-1][0], "explain")

    def test_stop_question_keeps_partial_context_and_allows_next_question(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.on_question("请详细解释。")
        c.llm.chunk.emit("chat", "回答的第一部分。")
        c.popup._stops["chat"].click()
        self.assertEqual(c.llm.cancellations[-1], ("chat",))
        self.assertIsNone(c._chat_pending_question)
        self.assertTrue(c.popup.btn_send.isEnabled())
        self.assertFalse(c.popup._stops["chat"].isVisible())
        self.assertIn("回答的第一部分。", c.popup.chat_view.toPlainText())
        self.assertEqual(len(c._chat_history), 2)
        self.assertIn("回答未完成", c._chat_history[-1]["content"])
        c.popup.question_input.setPlainText("这部分是什么意思？")
        QTest.keyClick(c.popup.question_input, Qt.Key_Return)
        self.assertEqual(c.llm.requests[-1][1], "这部分是什么意思？")
        self.assertIn("回答的第一部分。", c.llm.requests[-1][2][-2]["content"])
        self.assertTrue(c.popup._stops["chat"].isVisible())
        self.assertFalse(c.popup.btn_send.isEnabled())

    def test_stop_before_first_chunk_and_repeat_stop_are_safe(self):
        c = self.controller
        self.open_selection()
        c.popup.tabs.setCurrentIndex(2)
        c.on_question("一个问题。")
        c.popup._stops["chat"].click()
        cancellations = len(c.llm.cancellations)
        c.on_stop("chat")
        self.assertEqual(len(c.llm.cancellations), cancellations)
        self.assertTrue(c.popup.btn_send.isEnabled())
        self.assertFalse(c.popup.is_pending("chat"))
        c.popup.question_input.setPlainText("下一个问题。")
        c.popup.btn_send.click()
        self.assertEqual(c.llm.requests[-1][1], "下一个问题。")

    def test_stop_buttons_reset_after_completion_failure_and_new_selection(self):
        c = self.controller
        self.open_selection()
        self.assertTrue(c.popup._stops["translate"].isVisible())
        c.llm.finished.emit("translate", "")
        self.assertFalse(c.popup._stops["translate"].isVisible())
        c.popup.tabs.setCurrentIndex(1)
        c.llm.failed.emit("explain", "网络错误")
        self.assertFalse(c.popup.is_pending("explain"))
        self.assertFalse(c.popup._stops["explain"].isVisible())
        c.popup.tabs.setCurrentIndex(2)
        c.on_question("请解释。")
        self.open_selection("A new selection.")
        self.assertEqual(c.popup._pending, {"translate"})
        self.assertTrue(c.popup._stops["chat"].isHidden())
        self.assertTrue(c.popup._stops["explain"].isHidden())


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

    def test_cancel_drops_queued_chunks_completion_and_errors(self):
        started, release = threading.Event(), threading.Event()
        received = []

        def fake_stream(cfg, kind, text, **kwargs):
            started.set()
            release.wait(2)
            return "late result"

        with patch.object(llm, "stream_chat", fake_stream):
            client = llm.LlmClient({})
            for signal in (client.chunk, client.finished, client.failed):
                signal.connect(lambda kind, value: received.append(value))
            try:
                client.request("explain", "old")
                self.assertTrue(started.wait(1))
                old_id = client._current_id("explain")
                for event in ("chunk", "finished", "failed"):
                    client._delivery.emit(event, old_id, "explain", "queued late result")
                client.cancel("explain")
                release.set()
                QTest.qWait(30)
                self.assertEqual(received, [])
            finally:
                release.set()
                client.close()
                for worker in client._workers.values():
                    worker.join(1)
                client.deleteLater()

    def test_cancel_does_not_block_ui_while_connection_close_waits(self):
        closing, release = threading.Event(), threading.Event()

        class BlockingConnection:
            sock = None

            def close(self):
                closing.set()
                release.wait(2)

        client = llm.LlmClient({})
        try:
            client._workers["chat"]._attach_conn(BlockingConnection())
            start = time.perf_counter()
            client.cancel("chat")
            self.assertLess(time.perf_counter() - start, 0.2)
            self.assertTrue(closing.wait(1))
            self.assertFalse(release.is_set())
        finally:
            release.set()
            client.close()
            for worker in client._workers.values():
                worker.join(1)
            client.deleteLater()

    def test_stop_during_connect_does_not_wait_for_model_response(self):
        stopped = threading.Event()

        class ConnectingConnection:
            sock = None

            def request(self, *args, **kwargs):
                stopped.set()  # 模拟用户在连接建立期间点击停止。

            def close(self):
                pass

            def getresponse(self):
                raise AssertionError("已经停止的请求不应继续等待响应")

        with patch.object(llm.http.client, "HTTPConnection", return_value=ConnectingConnection()):
            with self.assertRaises(llm._StreamAborted):
                llm.stream_chat(deepcopy(huayi.DEFAULTS), "explain", "long text",
                                cancelled=stopped.is_set)


if __name__ == "__main__":
    unittest.main()
