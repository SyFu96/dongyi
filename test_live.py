"""真实本地模型与窗口联调：uv run python test_live.py。

不安装/修改依赖，不启动全局输入监听；自动验证翻译与两轮追问。
"""

import json
from pathlib import Path
import tempfile
import time

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import win32gui

import app as huayi
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


def main():
    qt = QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    cfg = huayi.load_config()
    qt.setStyleSheet(app_theme_qss(cfg["theme"]))
    controller = huayi.App(cfg)
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
        controller.popup.question_input.setText("请只回答一个词：stores 在这个句子里是什么意思？")
        controller.popup.btn_send.click()
        first = wait_done(controller, "chat")
        assert first.strip() and len(controller._chat_history) == 2
        controller.popup.question_input.setText("刚才那个英文词是什么？请只回答英文词。")
        controller.popup.btn_send.click()
        second = wait_done(controller, "chat")
        assert "stores" in second.lower(), second
        assert len(controller._chat_history) == 4
        preview_dir = Path(tempfile.mkdtemp(prefix="huayi-ui-"))
        preview = preview_dir / "popup.png"
        controller.popup.grab().save(str(preview))
        print(json.dumps({"translation": translation, "first_answer": first,
                          "second_answer": second, "preview": str(preview)}, ensure_ascii=True))
    finally:
        controller.llm.close()
        for worker in controller.llm._workers.values():
            worker.join(2)
        for widget in (controller.popup, controller.status, controller.icon, controller.toast):
            widget.hide()
        controller.tray.hide()


if __name__ == "__main__":
    main()
