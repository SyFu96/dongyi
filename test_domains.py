# -*- coding: utf-8 -*-
"""领域适配核心逻辑测试：术语表解析/匹配、领域配置解析。"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

import domains


def write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8-sig")


class GlossaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_parse_bom_comments_quotes_and_invalid_rows(self):
        path = self.dir / "g.csv"
        write_csv(path, (
            "# 注释行\n"
            "SEI,固体电解质界面,缩写可保留\n"
            "\n"
            "只有一列\n"
            "空译文,\n"
            '"quoted, term","译文,带逗号"\n'
            "intercalation,嵌入\n"
            "SEI,固体电解质界面相\n"  # 后行覆盖前行
        ))
        entries = domains.load_glossary(path)
        got = {e[0]: (e[1], e[2]) for e in entries}
        self.assertEqual(len(entries), 3)
        self.assertEqual(got["SEI"], ("固体电解质界面相", ""))  # 覆盖生效且备注清空
        self.assertEqual(got["quoted, term"], ("译文,带逗号", ""))
        self.assertEqual(got["intercalation"], ("嵌入", ""))

    def test_missing_file_returns_empty(self):
        self.assertEqual(domains.load_glossary(self.dir / "nope.csv"), [])

    def test_hot_reload_on_file_change(self):
        path = self.dir / "g.csv"
        write_csv(path, "a,甲\n")
        self.assertEqual(len(domains.load_glossary(path)), 1)
        time.sleep(0.02)
        write_csv(path, "a,甲\nb,乙\n")
        self.assertEqual(len(domains.load_glossary(path)), 2)

    def test_match_case_insensitive_longest_first(self):
        glossary = [
            ("SEI", "固体电解质界面", ""),
            ("solid electrolyte interphase", "固体电解质界面相", ""),
            ("intercalation", "嵌入", ""),
        ]
        hits = domains.match_terms("The SEI forms during formation.", glossary)
        self.assertEqual([h[0] for h in hits], ["SEI"])
        text = "The solid electrolyte interphase (SEI) grows during cycling and intercalation."
        hits = domains.match_terms(text, glossary)
        self.assertEqual([h[0] for h in hits][:2],
                         ["solid electrolyte interphase", "intercalation"])
        self.assertEqual(domains.match_terms("无关文本", glossary), [])

    def test_match_respects_ascii_word_boundaries(self):
        glossary = [
            ("formation", "化成", ""),
            ("intercalation", "嵌入", ""),
            ("deintercalation", "脱嵌", ""),
            ("SEI", "固体电解质界面", ""),
            ("state of charge", "荷电状态", ""),
        ]
        # formation 不得命中 information
        self.assertEqual(domains.match_terms("Please see the information page.", glossary), [])
        # intercalation 不得命中 deintercalation，反之要命中
        hits = domains.match_terms("lithium deintercalation process", glossary)
        self.assertEqual([h[0] for h in hits], ["deintercalation"])
        hits = domains.match_terms("lithium intercalation process", glossary)
        self.assertEqual([h[0] for h in hits], ["intercalation"])
        # 缩写后接中文（词边界由 ASCII 字母数字界定，中文不算边界字符）
        hits = domains.match_terms("SEI膜的生长", glossary)
        self.assertEqual([h[0] for h in hits], ["SEI"])
        # 多词术语容忍换行与连续空白
        hits = domains.match_terms("the state\nof   charge is low", glossary)
        self.assertEqual([h[0] for h in hits], ["state of charge"])

    def test_match_limit(self):
        glossary = [(f"t{i}", f"译{i}", "") for i in range(80)]
        hits = domains.match_terms(" ".join(f"t{i}" for i in range(80)), glossary)
        self.assertEqual(len(hits), domains.MAX_TERMS_INJECTED)

    def test_long_fields_truncated_and_budgeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.csv"
            write_csv(path, "a," + "超" * 500 + "\n")
            entries = domains.load_glossary(path)
            self.assertEqual(len(entries[0][1]), domains.MAX_FIELD_CHARS)
        # 注入总预算
        matches = [(f"term{i}", "译" * 100, "") for i in range(50)]
        text = domains.format_glossary(matches, budget=1000)
        self.assertLessEqual(len(text), 1000 + 100)

    def test_format_glossary(self):
        text = domains.format_glossary([
            ("SEI", "固体电解质界面", "缩写可保留"),
            ("intercalation", "嵌入", ""),
        ])
        self.assertIn("术语对照", text)
        self.assertIn("- SEI → 固体电解质界面（缩写可保留）", text)
        self.assertIn("- intercalation → 嵌入", text)
        self.assertEqual(domains.format_glossary([]), "")


class DomainConfigTests(unittest.TestCase):
    def test_enabled_domains_filters_invalid(self):
        cfg = {
            "domains": {
                "battery": {"name": "电池", "enabled": True},
                "bad id with space": {"name": "坏id"},
                "../escape": {"name": "路径穿越"},
                "disabled_one": {"name": "停用", "enabled": False},
                "ok_default": {"name": "默认启用"},
            }
        }
        ids = [did for did, _ in domains.enabled_domains(cfg)]
        self.assertEqual(ids, ["battery", "ok_default"])
        self.assertFalse(domains.valid_id("../escape"))
        self.assertTrue(domains.valid_id("tcm_2026"))

    def test_resolve_active_falls_back_to_general(self):
        cfg = {"domains": {"battery": {"name": "电池", "enabled": True}},
               "active_domain": "missing"}
        self.assertEqual(domains.resolve_active(cfg), "")
        cfg["active_domain"] = "battery"
        self.assertEqual(domains.resolve_active(cfg), "battery")
        cfg["domains"]["battery"]["enabled"] = False
        self.assertEqual(domains.resolve_active(cfg), "")

    def test_matched_glossary_text_default_and_custom_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_csv(base / "glossaries" / "med.csv", "heart failure,心力衰竭\n")
            dom = {"name": "医学"}
            text = domains.matched_glossary_text(base, "med", dom, "Chronic heart failure")
            self.assertIn("heart failure → 心力衰竭", text)
            # 显式 glossary_file（绝对路径）
            write_csv(base / "my.csv", "HF,心力衰竭\n")
            dom2 = {"name": "医学", "glossary_file": str(base / "my.csv")}
            text = domains.matched_glossary_text(base, "med", dom2, "HF patients")
            self.assertIn("HF → 心力衰竭", text)


if __name__ == "__main__":
    unittest.main()
