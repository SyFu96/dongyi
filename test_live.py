"""真实本地模型与窗口联调：uv run python test_live.py。

不安装/修改依赖，不启动全局输入监听；验证翻译、连续追问、停止生成和放大阅读。
"""

import json
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import win32gui

import app as dongyi
from capture import Selection
from popup import app_theme_qss


def wait_done(controller, kind):
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        QTest.qWait(50)
        status = controller.popup._statuses[kind].text()
        if status.startswith("完成"):
            return controller.popup.result_text(kind)
        if controller.popup._retries[kind].isVisible():
            raise AssertionError(status)
    raise AssertionError(f"{kind} 未在等待时间内完成")


def stop_after_first_chunk(controller, kind):
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if controller.popup.result_text(kind):
            break
        if controller.popup._retries[kind].isVisible():
            raise AssertionError(controller.popup._statuses[kind].text())
    else:
        raise AssertionError(f"{kind} 未输出首段内容")
    assert controller.popup.is_pending(kind), "回答过短，无法验证中途停止"
    start = time.perf_counter()
    controller.popup._stops[kind].click()
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2, elapsed
    partial = controller.popup.result_text(kind)
    QTest.qWait(500)
    assert controller.popup.result_text(kind) == partial, "停止后仍在追加内容"
    assert not controller.popup.is_pending(kind)
    assert controller.popup._statuses[kind].text().startswith("已停止")
    return round(elapsed * 1000, 2)


def main():
    qt = QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    cfg = dongyi.load_config()
    qt.setStyleSheet(app_theme_qss(cfg["theme"]))
    controller = dongyi.App(cfg)
    try:
        controller._sel = Selection(text="The battery stores energy.")
        controller._icon_anchor = (300, 250)
        controller._open_popup("translate")
        translation = wait_done(controller, "translate")
        assert translation.strip()
        assert win32gui.IsWindowVisible(int(controller.popup.winId()))
        controller.popup.btn_pin.click()
        controller.on_mouse_down({"phys": (-5000, -5000)})
        assert controller.popup.isVisible()
        controller.popup.tabs.setCurrentIndex(2)
        editor = controller.popup.question_input
        editor.insertPlainText("请只回答一个词：")
        QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
        editor.insertPlainText("stores 在这个句子里是什么意思？")
        assert controller._chat_pending_question is None
        QTest.keyClick(editor, Qt.Key_Return)
        first = wait_done(controller, "chat")
        assert first.strip() and len(controller._chat_history) == 2
        controller.popup.question_input.setPlainText("刚才那个英文词是什么？请只回答英文词。")
        controller.popup.btn_send.click()
        second = wait_done(controller, "chat")
        assert "stores" in second.lower(), second
        assert len(controller._chat_history) == 4
        controller.popup.resize(760, 580)
        controller.popup.tabs.setCurrentIndex(1)
        explanation_stop_ms = stop_after_first_chunk(controller, "explain")
        controller.popup.tabs.setCurrentIndex(2)
        controller.popup.question_input.setPlainText("请详细写出电池储能的原理、应用和注意事项，至少2000字。")
        controller.popup.btn_send.click()
        question_stop_ms = stop_after_first_chunk(controller, "chat")
        assert controller.popup.btn_send.isEnabled()
        assert controller._chat_pending_question is None
        controller.popup.question_input.setPlainText("不用继续长篇回答了，请只回答英文单词 OK。")
        controller.popup.btn_send.click()
        resumed = wait_done(controller, "chat")
        assert resumed.strip(), resumed
        assert len(controller._chat_history) == 8
        controller.popup.tabs.setCurrentIndex(1)
        old_history = list(controller._chat_history)
        next_source = "A capacitor stores electrical energy."
        controller.on_captured({"req": {"purpose": "icon", "phys": (100, 100)},
                                "sel": Selection(text=next_source)})
        assert controller.icon.isVisible()
        assert controller._sel.text == "The battery stores energy."
        assert controller._chat_history == old_history
        controller.icon.clicked.emit()
        next_translation = wait_done(controller, "translate")
        assert next_translation.strip()
        assert controller.popup._source_text == next_source
        assert controller._chat_history == []
        assert not controller.icon.isVisible()
        preview_dir = Path(tempfile.mkdtemp(prefix="dongyi-ui-"))
        preview = preview_dir / "popup.png"
        controller.popup.grab().save(str(preview))
        print(json.dumps({"translation": translation, "first_answer": first,
                          "second_answer": second, "explanation_stop_ms": explanation_stop_ms,
                          "question_stop_ms": question_stop_ms, "answer_after_stop": resumed,
                          "new_selection_while_pinned": "PASS", "next_translation": next_translation,
                          "resized": [controller.popup.width(), controller.popup.height()],
                          "preview": str(preview)}, ensure_ascii=True))
    finally:
        controller.llm.close()
        for worker in controller.llm._workers.values():
            worker.join(2)
        for widget in (controller.popup, controller.status, controller.icon, controller.toast):
            widget.hide()
        controller.tray.hide()


if __name__ == "__main__":
    main()
