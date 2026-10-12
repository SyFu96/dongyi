"""离线渲染界面 PNG，使用示例数据，不读取密钥或请求模型。

在项目根执行：uv run python tools/preview_ui.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from popup import PopupWindow, app_theme_qss
from settings import SettingsWindow


def main():
    app = QApplication([])
    out = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "ui-refresh"
    out.mkdir(parents=True, exist_ok=True)
    source = "The solid electrolyte interphase (SEI) plays a crucial role in the cycling stability of lithium-ion batteries."
    translation = "固体电解质界面膜（SEI）对锂离子电池的循环稳定性起着关键作用。"
    cfg = {
        "popup": {"width": 520, "height": 420}, "theme": "dark",
        "model": "qwen3:8b", "base_url": "http://localhost:11434",
        "active_domain": "battery", "domains": {
            "battery": {"name": "电池 / 能源", "enabled": True, "note": "按电池领域学术惯例翻译。",
                        "kb_dirs": [], "kb_enabled": True, "kb_for_translate": False},
        },
    }
    for theme in ("dark", "light"):
        cfg["theme"] = theme
        app.setStyleSheet(app_theme_qss(theme))
        window = PopupWindow(cfg)
        window.set_domains([("", "通用"), ("battery", "电池 / 能源")], "battery")
        window.open_at(0, 0, source, False, "translate")
        window.append_chunk("translate", translation)
        window.mark_done("translate")
        window.set_backend("电池 / 能源 · 本地 · qwen3:8b")
        for kind in window.KINDS:
            window.tabs.setCurrentIndex(window.KINDS.index(kind))
            if kind == "explain":
                window.append_chunk(kind, "SEI 是电极与电解液之间形成的界面膜。\n\n它允许锂离子通过，同时抑制电解液持续分解，从而影响电池的循环寿命。")
                window.mark_done(kind)
            elif kind == "chat":
                window.begin_question("为什么 SEI 会影响循环稳定性？")
                window.append_chunk(kind, "稳定的 SEI 可以减少电解液消耗与活性锂损失，帮助电池维持容量。")
                window.mark_done(kind)
                window.chat_view.verticalScrollBar().setValue(0)
            elif kind == "input":
                window.input_editor.setPlainText(source)
                window.append_chunk(kind, translation)
                window.mark_done(kind)
            app.processEvents()
            window.grab().save(str(out / f"{theme}-{kind}.png"))
        window.close_now()
        window.deleteLater()
        with patch.object(SettingsWindow, "_refresh_local_models"):
            settings = SettingsWindow(cfg)
            settings.reload()
        settings.show()
        app.processEvents()
        settings.grab().save(str(out / f"{theme}-settings.png"))
        settings.close()
        settings.deleteLater()
    app.processEvents()
    print(out)


if __name__ == "__main__":
    main()
