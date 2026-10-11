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

    def test_path_for_rejects_unsafe_ids(self):
        self.assertEqual(self.store.path_for("battery").name, "battery.jsonl")
        self.assertEqual(self.store.path_for("").name, "general.jsonl")
        self.assertEqual(self.store.path_for("../evil").name, "general.jsonl")

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
