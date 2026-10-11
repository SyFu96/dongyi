# -*- coding: utf-8 -*-
"""翻译记忆测试：读写、相似度检索、注入格式与阈值。"""

import tempfile
import unittest
from pathlib import Path

import tm


class TmStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = tm.TmStore(Path(self.tmp.name) / "tm")
        self.addCleanup(self.tmp.cleanup)

    def test_append_count_clear_and_domain_isolation(self):
        self.assertTrue(self.store.append("battery", "src", "tgt"))
        self.assertTrue(self.store.append("battery", "src2", "tgt2"))
        self.store.append("", "general src", "general tgt")
        self.assertEqual(self.store.count("battery"), 2)
        self.assertEqual(self.store.count(""), 1)
        self.assertFalse(self.store.append("battery", "", ""))
        self.assertEqual(self.store.clear("battery"), 2)
        self.assertEqual(self.store.count("battery"), 0)
        self.assertEqual(self.store.count(""), 1)  # 其他领域不受影响

    def test_path_for_rejects_unsafe_ids_and_isolates_general(self):
        self.assertEqual(self.store.path_for("battery").name, "dom_battery.jsonl")
        self.assertEqual(self.store.path_for("").name, "general.jsonl")
        self.assertEqual(self.store.path_for("../evil").name, "general.jsonl")
        # id "general" 不得占用通用模式的命名空间。
        # （Battery/battery 大小写碰撞由 domains.enabled_domains 在配置层去重防止）
        self.assertEqual(self.store.path_for("general").name, "dom_general.jsonl")

    def test_legacy_file_is_migrated_on_access(self):
        # 旧版文件名 tm/<id>.jsonl：首次访问时整体迁移到 dom_<id>.jsonl
        legacy = self.store.path_for("battery").parent / "battery.jsonl"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text('{"src": "old", "tgt": "旧句对"}\n', encoding="utf-8")
        self.assertEqual(self.store.count("battery"), 1)
        self.assertFalse(legacy.exists())  # 已改名迁移
        self.assertTrue(self.store.path_for("battery").exists())
        text = self.store.example_context("battery", "old sentence")
        self.assertIn("旧句对", text)

    def test_new_file_wins_when_both_exist(self):
        new_path = self.store.path_for("battery")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text('{"src": "new", "tgt": "新文件"}\n', encoding="utf-8")
        legacy = new_path.parent / "battery.jsonl"
        legacy.write_text('{"src": "old", "tgt": "旧文件"}\n', encoding="utf-8")
        self.assertEqual(self.store.count("battery"), 1)  # 以新文件为准
        self.assertIn("新文件", self.store.example_context("battery", "new"))

    def test_corrupted_records_and_encoding_do_not_break_reads(self):
        path = self.store.path_for("battery")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"src": "正常", "tgt": "normal"}\n'
            '{"src": 123, "tgt": "数字原文应被跳过"}\n'
            '{"src": "无译文"}\n'
            "不是 JSON 的一行\n"
            '{"src": "ok", "tgt": "好"}\n',
            encoding="utf-8")
        self.assertEqual(self.store.count("battery"), 2)
        # 二进制垃圾（解码失败）也不抛异常
        path.write_bytes(b"\xff\xfe\x00garbage")
        self.assertEqual(self.store.count("battery"), 0)
        self.assertEqual(self.store.example_context("battery", "anything"), "")

    def test_similarity(self):
        self.assertGreater(tm.similarity("SEI 膜生长机制", "SEI 膜生长"), 0.5)
        self.assertLess(tm.similarity("电池储能", "今天天气不错"), 0.15)
        self.assertEqual(tm.similarity("", "abc"), 0.0)

    def test_example_context_threshold_and_format(self):
        self.store.append("battery", "The SEI film grows during cycling.",
                          "SEI 膜在循环过程中生长。")
        self.store.append("battery", "Completely unrelated sentence about cooking.",
                          "完全无关的做饭句子。")
        text = self.store.example_context("battery", "The SEI film grows during cycling.")
        self.assertIn("SEI", text)
        self.assertIn("原文：", text)
        self.assertIn("译文：", text)
        # 不相似文本不注入
        self.assertEqual(self.store.example_context("battery", "量子纠缠实验"), "")
        # 不存在的领域/空文本
        self.assertEqual(self.store.example_context("nope", "anything"), "")
        self.assertEqual(self.store.example_context("battery", ""), "")

    def test_long_pairs_excluded(self):
        self.store.append("", "长" * 800, "译" * 800)
        self.assertEqual(self.store.example_context("", "长" * 800), "")


if __name__ == "__main__":
    unittest.main()
