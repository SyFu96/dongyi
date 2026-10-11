# -*- coding: utf-8 -*-
"""领域适配集成测试：配置种入、_compose_system 组装链路、切换与持久化。"""

import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import app as dongyi
import domains
from capture import Selection
from test_features import FakeLlm


class ConfigSeedTests(unittest.TestCase):
    """load_config 的领域种入：旧配置升级补 battery，用户显式写过 domains 则尊重。"""

    def test_old_config_seeded_and_explicit_domains_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text('{"provider": "ollama"}', encoding="utf-8")
            with patch.object(dongyi, "CONFIG_PATH", cfg_path):
                cfg = dongyi.load_config()
            self.assertIn("battery", cfg["domains"])
            self.assertEqual(cfg["active_domain"], "")

            cfg_path.write_text('{"domains": {"mine": {"name": "我的"}}}', encoding="utf-8")
            with patch.object(dongyi, "CONFIG_PATH", cfg_path):
                cfg2 = dongyi.load_config()
            self.assertNotIn("battery", cfg2["domains"])
            self.assertIn("mine", cfg2["domains"])

    def test_missing_config_written_with_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            with patch.object(dongyi, "CONFIG_PATH", cfg_path):
                cfg = dongyi.load_config()
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
        self.cfg = deepcopy(dongyi.DEFAULTS)
        self.cfg["domains"] = {"battery": {
            "name": "电池/能源", "note": "电池与能源领域文献。", "enabled": True,
            "glossary_file": "glossaries/battery.csv", "kb_dirs": [],
            "kb_enabled": False, "kb_for_translate": False}}
        self.cfg["active_domain"] = ""
        for p in (
            patch.object(dongyi.llm, "LlmClient", FakeLlm),
            patch.object(dongyi.startup, "is_enabled", return_value=False),
            patch.object(dongyi, "DATA_DIR", self.base),
            patch.object(dongyi, "CONFIG_PATH", self.base / "config.json"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.controller = dongyi.App(self.cfg)

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
        # M5 回归：解释不是译文，不能进翻译记忆——按钮不出现，且即使有解释
        # 内容、保存入口被误触发也必须拒绝（空内容提前返回不算证据）
        from PySide6.QtWidgets import QPushButton
        c = self.controller
        self.open_selection()
        translate_buttons = [b.text() for b in c.popup.tabs.widget(0).findChildren(QPushButton)]
        explain_buttons = [b.text() for b in c.popup.tabs.widget(1).findChildren(QPushButton)]
        self.assertIn("存为记忆", translate_buttons)
        self.assertNotIn("存为记忆", explain_buttons)
        c.set_domain("battery")
        c.popup.append_chunk("explain", "这是一段已经生成的解释内容。")
        c.popup.mark_done("explain")
        constructed = []

        class ShouldNotConstruct:
            def __init__(self, *args, **kwargs):
                constructed.append(args)

            def exec(self):
                return self.Accepted

            Accepted = 1

        with patch.object(dongyi, "TmEditDialog", ShouldNotConstruct):
            c.on_tm_save("explain")
        self.assertEqual(constructed, [])
        self.assertEqual(c.tmstore.count("battery"), 0)

    def test_tm_save_snapshots_source_against_dialog_reentry(self):
        # M6 回归：exec() 的嵌套事件循环期间可能收到新取词结果或学科切换，
        # 保存进记忆的原文与领域必须是打开对话框那一刻的快照
        c = self.controller
        c.set_domain("battery")
        self.open_selection("The SEI forms here.")
        c.popup.append_chunk("translate", "SEI 在此形成。")
        c.popup.mark_done("translate")

        captured: dict = {}

        class FakeDialog:
            Accepted = 1  # 与 QDialog.DialogCode.Accepted 一致

            def __init__(self, source, translation):
                captured["source"] = source
                self._translation = translation

            def exec(self):
                # 模拟对话框打开期间：新取词到达 + 用户切换学科到通用
                c._sel = Selection(text="A NEW selection arrived mid-dialog.")
                c._cfg["active_domain"] = ""
                return self.Accepted

            def translation(self):
                return self._translation

        with patch.object(dongyi, "TmEditDialog", FakeDialog):
            c.on_tm_save("translate")
        entries = c.tmstore._load("battery")[0]  # 领域快照 = battery
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["src"], "The SEI forms here.")  # 快照，不是新取词
        self.assertEqual(entries[0]["tgt"], "SEI 在此形成。")
        # 通用模式的记忆不受影响
        self.assertEqual(c.tmstore._load("")[0], [])

    def test_kb_pending_dirs_are_actually_processed(self):
        # M3 回归：索引忙时到来的目录变更，必须在工作循环结束后被真实补跑
        c = self.controller
        docs1 = self.base / "docs1"
        docs1.mkdir()
        (docs1 / "a.txt").write_text("first corpus text", encoding="utf-8")
        docs2 = self.base / "docs2"
        docs2.mkdir()
        (docs2 / "b.txt").write_text("second corpus text", encoding="utf-8")
        calls: list[list[str]] = []
        gate = threading.Event()
        real_refresh = c.kb.refresh

        def slow_refresh(dirs):
            calls.append(list(dirs))
            result = real_refresh(dirs)
            if len(calls) == 1:
                gate.wait(2)  # 第一轮挂起，制造 busy 窗口
            return result

        c._cfg["domains"]["battery"]["kb_enabled"] = True
        c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs1)]
        with patch.object(c.kb, "refresh", slow_refresh):
            c._maybe_refresh_kb()  # 第 1 轮（阻塞在 gate）
            deadline = time.time() + 2
            while not calls and time.time() < deadline:
                QTest.qWait(10)
            self.assertEqual(len(calls), 1)
            c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs2)]
            c._maybe_refresh_kb()  # busy → 目录暂存为 pending
            gate.set()             # 放行第 1 轮
            # 等到第 2 轮开始且工作循环彻底退出（busy=False、pending 清空）
            deadline = time.time() + 3
            while (len(calls) < 2 or c._kb_busy) and time.time() < deadline:
                QTest.qWait(10)
        # pending 真实补跑（而不只是入队）
        self.assertEqual(len(calls), 2, f"pending 未被补跑：{calls}")
        self.assertEqual(calls[1], [str(docs2)])
        self.assertFalse(c._kb_busy)
        self.assertIsNone(c._kb_pending_dirs)
        self.assertIn("second corpus", c.kb.search("second corpus")[0]["text"])

    def test_kb_failure_hands_over_pending_and_keeps_signature_clean(self):
        # M3 回归：A 失败时已排队的 B 必须补跑（不丢待办）；失败轮不提交签名
        c = self.controller
        docs1 = self.base / "fail1"
        docs1.mkdir()
        (docs1 / "a.txt").write_text("first corpus text", encoding="utf-8")
        docs2 = self.base / "fail2"
        docs2.mkdir()
        (docs2 / "b.txt").write_text("second corpus text", encoding="utf-8")
        calls: list[list[str]] = []
        gate = threading.Event()
        real_refresh = c.kb.refresh

        def flaky_refresh(dirs):
            calls.append(list(dirs))
            if len(calls) == 1:
                gate.wait(2)  # 挂在抛错**前**：制造稳定的"A 在途"窗口
                raise RuntimeError("simulated index failure")
            return real_refresh(dirs)

        c._cfg["domains"]["battery"]["kb_enabled"] = True
        c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs1)]
        with patch.object(c.kb, "refresh", flaky_refresh):
            c._maybe_refresh_kb()  # A（挂起，将失败）
            deadline = time.time() + 2
            while not calls and time.time() < deadline:
                QTest.qWait(10)
            c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs2)]
            c._maybe_refresh_kb()  # A 还在途 → B 进 pending
            # 中间态断言（A 抛错前）：B 确实已排队、A 确实未提交签名——
            # 否则"失败后补跑"可能只是失败后才启动的普通任务
            self.assertEqual(calls, [[str(docs1)]])
            self.assertEqual(c._kb_inflight, [str(docs1)])
            self.assertEqual(c._kb_pending_dirs, [str(docs2)])
            self.assertEqual(c._kb_dirs_signature, ())
            gate.set()  # 放行 A → 抛错 → 交接 B
            deadline = time.time() + 3
            while (len(calls) < 2 or c._kb_busy) and time.time() < deadline:
                QTest.qWait(10)
        self.assertEqual(calls[0], [str(docs1)])
        self.assertEqual(calls[1], [str(docs2)], "失败后 pending 被丢弃，未补跑")
        self.assertFalse(c._kb_busy)
        # 签名最终 = 成功轮 B；失败轮 A 从未提交
        self.assertEqual(c._kb_dirs_signature, (str(docs2),))
        self.assertIn("second corpus", c.kb.search("second corpus")[0]["text"])

    def test_kb_revert_while_inflight_is_not_short_circuited(self):
        # M3 回归：已完成签名 A、在途 B 时改回 A——不能被"签名已达成"短路，
        # 否则 B 完成后索引与当前配置不一致
        c = self.controller
        docs_a = self.base / "rev_a"
        docs_a.mkdir()
        (docs_a / "a.txt").write_text("alpha corpus text", encoding="utf-8")
        docs_b = self.base / "rev_b"
        docs_b.mkdir()
        (docs_b / "b.txt").write_text("beta corpus text", encoding="utf-8")
        calls: list[list[str]] = []
        gate = threading.Event()
        real_refresh = c.kb.refresh

        def slow_refresh(dirs):
            calls.append(list(dirs))
            result = real_refresh(dirs)
            if len(calls) == 2:
                gate.wait(2)  # 挂起 B 轮，制造"签名=A、在途=B"窗口
            return result

        c._cfg["domains"]["battery"]["kb_enabled"] = True
        c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs_a)]
        with patch.object(c.kb, "refresh", slow_refresh):
            c._maybe_refresh_kb()  # A 完成，签名 = A
            deadline = time.time() + 2
            while not calls and time.time() < deadline:
                QTest.qWait(10)
            c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs_b)]
            c._maybe_refresh_kb()  # B 开始（阻塞在 gate）
            deadline = time.time() + 2
            while len(calls) < 2 and time.time() < deadline:
                QTest.qWait(10)
            self.assertEqual(c._kb_inflight, [str(docs_b)])
            c._cfg["domains"]["battery"]["kb_dirs"] = [str(docs_a)]
            c._maybe_refresh_kb()  # 改回 A：必须排队，不能短路
            gate.set()
            deadline = time.time() + 3
            while (len(calls) < 3 or c._kb_busy) and time.time() < deadline:
                QTest.qWait(10)
        self.assertEqual(calls, [[str(docs_a)], [str(docs_b)], [str(docs_a)]],
                         f"改回 A 未被排队补跑：{calls}")
        self.assertEqual(c._kb_dirs_signature, (str(docs_a),))
        self.assertFalse(c._kb_busy)

    def test_kb_rebuild_none_uses_saved_config_and_empty_list_clears(self):
        # 复核新问题 1 的语义修复：None = 用已保存配置；[] = 用户刚清空全部目录
        c = self.controller
        c._cfg["domains"]["battery"]["kb_enabled"] = True
        c._cfg["domains"]["battery"]["kb_dirs"] = ["D:/some/dir"]
        captured: list = []
        with patch.object(c, "_start_kb_worker",
                          lambda dirs, signature=None: captured.append((list(dirs), signature))):
            c.on_kb_rebuild(None)
            c.on_kb_rebuild([])
        self.assertEqual(captured[0], (["D:/some/dir"], ("D:/some/dir",)))
        self.assertEqual(captured[1], ([], ()))  # 空列表不得回退到已保存配置


class SettingsFormRegressionTests(unittest.TestCase):
    """C1 回归：表单载入/切换领域的信号回写不得污染领域配置。"""

    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def _make_cfg(self):
        cfg = deepcopy(dongyi.DEFAULTS)
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
        window = dongyi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
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

    def test_rebuild_requests_union_of_all_enabled_domains(self):
        # 复核新问题 1：重建索引用全部启用领域的目录并集（共享索引），
        # 当前领域用表单实时值——不能只传当前领域把其他领域挤掉
        cfg = self._make_cfg()
        cfg["domains"]["d2"].update({"kb_dirs": ["D:/kb/two"], "kb_enabled": True,
                                     "enabled": True})
        window = dongyi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
        captured: list = []
        window.rebuild_requested.connect(lambda dirs: captured.append(list(dirs)))
        try:
            window.reload()
            combo = window.domain_combo
            combo.setCurrentIndex(combo.findData("d1"))
            window.kb_dirs.clear()          # 用户在表单里改了 d1 的目录（未保存）
            window.kb_dirs.addItem("D:/kb/edited")
            window._rebuild_kb()
            self.assertEqual(captured, [["D:/kb/edited", "D:/kb/two"]])
            # 当前领域在表单里被停用后，其目录退出并集
            window.domain_enabled.setChecked(False)
            window._rebuild_kb()
            self.assertEqual(captured[-1], ["D:/kb/two"])
        finally:
            window.hide()
            window.deleteLater()
            QTest.qWait(5)

    def test_domain_combo_dedups_case_insensitive_aliases(self):
        # m2 回归：大小写别名不进设置页，且保留者与运行时一致。
        # 必须按"D1 停用在前、d1 启用在后"构造——若启用者在前，
        # 简单的"取第一个"实现也能通过，测不出保留者偏好规则
        cfg = deepcopy(dongyi.DEFAULTS)
        cfg["domains"] = {
            "D1": {"name": "d1 的停用别名", "enabled": False, "kb_dirs": [],
                   "kb_enabled": False},
            "d1": {"name": "d1 正主", "enabled": True, "kb_dirs": [], "kb_enabled": False},
        }
        # 与运行时保留者一致：两层都应保留启用的 d1
        self.assertEqual([did for did, _ in domains.enabled_domains(cfg)], ["d1"])
        window = dongyi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
        try:
            window.reload()
            datas = [window.domain_combo.itemData(i)
                     for i in range(window.domain_combo.count())]
            lowers = [d.lower() for d in datas]
            self.assertEqual(len(lowers), len(set(lowers)))  # 无大小写重复
            self.assertEqual(datas, ["d1"])  # 停用别名不显示，保留启用正主
        finally:
            window.hide()
            window.deleteLater()
            QTest.qWait(5)

    def test_empty_domains_form_is_safe(self):
        cfg = self._make_cfg()
        cfg["domains"] = {}
        window = dongyi.SettingsWindow(cfg, Path(tempfile.gettempdir()), None, None)
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
