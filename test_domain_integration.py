# -*- coding: utf-8 -*-
"""领域适配集成测试：配置种入、_compose_system 组装链路、切换与持久化。"""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import app as huayi
from capture import Selection
from test_features import FakeLlm


class ConfigSeedTests(unittest.TestCase):
    """load_config 的领域种入：旧配置升级补 battery，用户显式写过 domains 则尊重。"""

    def test_old_config_seeded_and_explicit_domains_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text('{"provider": "ollama"}', encoding="utf-8")
            with patch.object(huayi, "CONFIG_PATH", cfg_path):
                cfg = huayi.load_config()
            self.assertIn("battery", cfg["domains"])
            self.assertEqual(cfg["active_domain"], "")

            cfg_path.write_text('{"domains": {"mine": {"name": "我的"}}}', encoding="utf-8")
            with patch.object(huayi, "CONFIG_PATH", cfg_path):
                cfg2 = huayi.load_config()
            self.assertNotIn("battery", cfg2["domains"])
            self.assertIn("mine", cfg2["domains"])

    def test_missing_config_written_with_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            with patch.object(huayi, "CONFIG_PATH", cfg_path):
                cfg = huayi.load_config()
            self.assertTrue(cfg_path.exists())
            self.assertIn("battery", cfg["domains"])


class DomainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "glossaries").mkdir()
        (self.base / "glossaries" / "battery.csv").write_text(
            "SEI,固体电解质界面,缩写可保留\nintercalation,嵌入\n", encoding="utf-8-sig")
        self.cfg = deepcopy(huayi.DEFAULTS)
        self.cfg["domains"] = {"battery": {
            "name": "电池/能源", "note": "电池与能源领域文献。", "enabled": True,
            "glossary_file": "glossaries/battery.csv", "kb_dirs": [],
            "kb_enabled": False, "kb_for_translate": False}}
        self.cfg["active_domain"] = ""
        for p in (
            patch.object(huayi.llm, "LlmClient", FakeLlm),
            patch.object(huayi.startup, "is_enabled", return_value=False),
            patch.object(huayi, "DATA_DIR", self.base),
            patch.object(huayi, "CONFIG_PATH", self.base / "config.json"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.controller = huayi.App(self.cfg)

    def tearDown(self):
        c = self.controller
        c._startup_retry.stop()
        c._keepalive.stop()
        c._debounce.stop()
        for window in (c.popup, c.icon, c.toast, c.status, c.settings):
            window.hide()
            window.deleteLater()
        c.tray.hide()
        c.deleteLater()
        QTest.qWait(5)

    def open_selection(self, text="The SEI forms during lithium intercalation."):
        c = self.controller
        c._sel = Selection(text=text)
        c._icon_anchor = (100, 100)
        c._open_popup("translate")
        QTest.qWait(5)

    def test_translate_composes_note_glossary_tm(self):
        c = self.controller
        c.set_domain("battery")
        self.open_selection()
        system = c.llm.requests[-1][2][0]["content"]
        self.assertTrue(system.startswith(c._cfg["prompts"]["translate"]))
        self.assertIn("电池与能源领域文献", system)
        self.assertIn("SEI → 固体电解质界面", system)
        self.assertIn("intercalation → 嵌入", system)

        # 翻译记忆：确认过的相似句对作为参考注入
        self.assertTrue(c.tmstore.append(
            "battery", "The SEI forms during lithium intercalation.", "SEI 在锂嵌入过程中形成。"))
        c.on_retry("translate")
        system = c.llm.requests[-1][2][0]["content"]
        self.assertIn("参考译例", system)
        self.assertIn("SEI 在锂嵌入过程中形成", system)

        # 切回通用：领域段全部消失
        c.set_domain("")
        c.on_retry("translate")
        system = c.llm.requests[-1][2][0]["content"]
        self.assertNotIn("电池与能源领域文献", system)
        self.assertNotIn("术语对照", system)

    def test_kb_context_injected_for_explain_when_enabled(self):
        c = self.controller
        c.set_domain("battery")
        docs = self.base / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "The solid electrolyte interphase suppresses lithium dendrites.", encoding="utf-8")
        c.kb.refresh([str(docs)])
        c._cfg["domains"]["battery"]["kb_enabled"] = True
        c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs)]
        self.open_selection("lithium dendrites suppression")
        c._dispatch("explain")
        system = c.llm.requests[-1][2][0]["content"]
        self.assertIn("用户知识库", system)
        self.assertIn("dendrites", system)
        # 翻译默认不检索知识库
        c.on_retry("translate")
        system = c.llm.requests[-1][2][0]["content"]
        self.assertNotIn("用户知识库", system)
        # 打开开关后翻译也检索
        c._cfg["domains"]["battery"]["kb_for_translate"] = True
        c.on_retry("translate")
        self.assertIn("用户知识库", c.llm.requests[-1][2][0]["content"])

    def test_chat_and_input_requests_include_domain_context(self):
        c = self.controller
        c.set_domain("battery")
        self.open_selection()
        c.on_question("这个句子是什么意思？")
        system = c.llm.requests[-1][2][0]["content"]
        self.assertIn("电池与能源领域文献", system)
        self.assertIn("SEI → 固体电解质界面", system)
        self.assertIn("原文：", system)

        c.on_input_translate("SEI intercalation", None)
        system = c.llm.requests[-1][2][0]["content"]
        self.assertIn("SEI → 固体电解质界面", system)
        self.assertNotIn("用户知识库", system)  # 输入翻译默认不检索

    def test_set_domain_updates_state_ui_and_persists(self):
        c = self.controller
        c.set_domain("battery")
        self.assertEqual(c._cfg["active_domain"], "battery")
        self.assertEqual(c.popup.domain_combo.currentData(), "battery")
        self.assertIn("电池/能源", c._backend_text("translate"))
        persisted = (self.base / "config.json").read_text(encoding="utf-8")
        self.assertIn('"active_domain": "battery"', persisted)
        # 托盘子菜单同步
        acts = [a.text() for a in c.tray.domain_menu.actions()]
        self.assertIn("通用", acts)
        self.assertIn("电池/能源", acts)
        # 无效/未启用领域回退通用
        c.set_domain("nonexistent")
        self.assertEqual(c._cfg["active_domain"], "")
        # 重复设置同值不重复写盘
        c.set_domain("")
        self.assertEqual(c._cfg["active_domain"], "")

    def test_popup_domain_combo_switch_emits_and_applies(self):
        c = self.controller
        index = c.popup.domain_combo.findData("battery")
        self.assertGreaterEqual(index, 0)
        c.popup.domain_combo.setCurrentIndex(index)  # 用户在下拉里选择
        self.assertEqual(c._cfg["active_domain"], "battery")

    def test_explain_page_has_no_tm_button_and_save_is_rejected(self):
        # M5 回归：解释不是译文，不能进翻译记忆
        from PySide6.QtWidgets import QPushButton
        c = self.controller
        self.open_selection()
        translate_buttons = [b.text() for b in c.popup.tabs.widget(0).findChildren(QPushButton)]
        explain_buttons = [b.text() for b in c.popup.tabs.widget(1).findChildren(QPushButton)]
        self.assertIn("存为记忆", translate_buttons)
        self.assertNotIn("存为记忆", explain_buttons)
        # 入口二次校验：即使收到 explain 的保存信号也不写入
        before = c.tmstore.count("battery")
        c.set_domain("battery")
        c.on_tm_save("explain")
        self.assertEqual(c.tmstore.count("battery"), before)

    def test_kb_dir_change_while_busy_is_not_lost(self):
        # M3 回归：索引忙时到来的目录变更必须被记录补跑，而不是被签名吞掉
        c = self.controller
        c._kb_busy = True
        try:
            c._maybe_refresh_kb()  # 启动时触发一次（busy → 进 pending）
            c._cfg["domains"]["battery"]["kb_enabled"] = True
            c._cfg["domains"]["battery"]["kb_dirs"] = [str(self.base / "docs")]
            c._maybe_refresh_kb()  # 目录变化 → 仍 busy → 记录 pending
            with c._kb_pending_lock:
                self.assertEqual(c._kb_pending_dirs, [str(self.base / "docs")])
        finally:
            c._kb_busy = False
            with c._kb_pending_lock:
                c._kb_pending_dirs = None


class SettingsFormRegressionTests(unittest.TestCase):
    """C1 回归：表单载入/切换领域的信号回写不得污染领域配置。"""

    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def _make_cfg(self):
        cfg = deepcopy(huayi.DEFAULTS)
        cfg["domains"] = {
            "d1": {"name": "领域一", "note": "说明一", "enabled": True,
                   "glossary_file": "", "kb_dirs": ["D:/kb/one"],
                   "kb_enabled": True, "kb_for_translate": False},
            "d2": {"name": "领域二", "note": "说明二", "enabled": False,
                   "glossary_file": "", "kb_dirs": [],
                   "kb_enabled": False, "kb_for_translate": True},
        }
        return cfg

    def test_open_switch_and_save_keeps_domains_intact(self):
        cfg = self._make_cfg()
        window = huayi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
        try:
            window.reload()
            combo = window.domain_combo
            # 多轮来回切换（旧 bug：切换后 kb_dirs/说明被上一个领域污染）
            for _ in range(3):
                combo.setCurrentIndex(combo.findData("d2"))
                combo.setCurrentIndex(combo.findData("d1"))
            window._on_save()
            d1, d2 = cfg["domains"]["d1"], cfg["domains"]["d2"]
            self.assertEqual(d1["note"], "说明一")
            self.assertEqual(d1["kb_dirs"], ["D:/kb/one"])
            self.assertTrue(d1["kb_enabled"])
            self.assertFalse(d1["kb_for_translate"])
            self.assertEqual(d2["note"], "说明二")
            self.assertEqual(d2["kb_dirs"], [])
            self.assertFalse(d2["enabled"])
            self.assertTrue(d2["kb_for_translate"])
        finally:
            window.hide()
            window.deleteLater()
            QTest.qWait(5)

    def test_empty_domains_form_is_safe(self):
        cfg = self._make_cfg()
        cfg["domains"] = {}
        window = huayi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
        try:
            window.reload()
            self.assertEqual(window.domain_combo.count(), 0)
            window._on_save()
            self.assertEqual(cfg["domains"], {})
        finally:
            window.hide()
            window.deleteLater()
            QTest.qWait(5)


if __name__ == "__main__":
    unittest.main()
