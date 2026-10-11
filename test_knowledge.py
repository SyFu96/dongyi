# -*- coding: utf-8 -*-
"""知识库（RAG）测试：分词、分块、索引增量更新、BM25 检索与注入门控。"""

import tempfile
import time
import unittest
from pathlib import Path

import knowledge


class TokenizeTests(unittest.TestCase):
    def test_mixed_tokens(self):
        tokens = knowledge.tokenize("The SEI膜 的 ionic conductivity")
        self.assertIn("sei", tokens)
        self.assertIn("the", tokens)
        self.assertIn("ionic", tokens)
        tokens = knowledge.tokenize("SEI膜生长")
        self.assertIn("sei", tokens)
        self.assertIn("膜生", tokens)
        self.assertIn("生长", tokens)
        self.assertEqual(knowledge.tokenize(""), [])
        self.assertEqual(knowledge.tokenize("。！、"), [])  # 纯标点无中文


class ChunkTests(unittest.TestCase):
    def test_paragraph_aggregation_and_hard_cap(self):
        paras = ["甲" * 300, "乙" * 260, "丙" * 400]
        chunks = knowledge.chunk_text("\n\n".join(paras))
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= knowledge.CHUNK_HARD + 10 for c in chunks))
        # 超长单段被切开
        long_one = "word " * 600  # 3000 字符
        pieces = knowledge.chunk_text(long_one)
        self.assertGreater(len(pieces), 1)

    def test_split_long_prefers_space(self):
        text = "aaaa bbbb cccc dddd"
        pieces = knowledge._split_long(text, 10)
        self.assertEqual(pieces, ["aaaa bbbb", "cccc dddd"])


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name) / "docs"
        self.index_dir = Path(self.tmp.name) / "kb_index"
        self.docs.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name: str, content: str) -> Path:
        path = self.docs / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_avgdl_counts_all_tokens_not_unique(self):
        # M1 回归：平均块长必须与评分的块长同口径（全部 token 数），
        # 否则重复词多的块被错误惩罚
        self._write("repeat.txt", "alpha alpha alpha alpha")
        self._write("once.txt", "beta gamma delta epsilon")
        store = knowledge.KnowledgeStore(self.index_dir)
        store.refresh([str(self.docs)])
        _chunks, _counts, _df, avgdl = store._ensure_stats()
        # repeat 块 4 个 token，once 块 4 个 token → 平均 4（旧实现会算成 2）
        self.assertAlmostEqual(avgdl, 4.0)
        hits = store.search("alpha", dirs=[str(self.docs)])
        self.assertTrue(hits)

    def test_excluded_paths_are_never_indexed(self):
        # M7 回归：config.json 等排除项不得进入索引（含密钥文件外发风险）
        secret = self._write("config.json", 'cloud api key sk-FAKE-SECRET-KEY battery')
        store = knowledge.KnowledgeStore(self.index_dir, exclude=[secret])
        stats = store.refresh([str(self.docs)])
        self.assertEqual(stats["files"], 0)
        self.assertEqual(store.search("FAKE-SECRET-KEY"), [])
        secret.unlink()  # 清掉上一段的文件，只验证下面的目录前缀排除
        # 目录前缀排除（目录可以不存在）
        store2 = knowledge.KnowledgeStore(
            self.index_dir / "s2", exclude=[self.docs / "sub"])
        self._write("keep.txt", "cathode material text")
        (self.docs / "sub").mkdir()
        self._write("sub/inner.md", "anode material text")
        store2.refresh([str(self.docs)])
        self.assertEqual(store2.stats()["files"], 1)
        self.assertEqual(store2.search("anode"), [])
        # 索引目录位于扫描范围内时整体排除自身（App 的真实场景：kb_index 在数据目录里）
        store3 = knowledge.KnowledgeStore(self.index_dir)
        store3.refresh([str(self.index_dir)])
        self.assertEqual(store3.stats()["files"], 0)
        self.assertEqual(store3.search("version"), [])

    def test_gbk_text_falls_back_to_gb18030(self):
        # m3 回归：GBK 中文不能被 errors=replace 洗成乱码照常索引
        path = self.docs / "gbk.txt"
        path.write_text("磷酸铁锂电池的正极材料", encoding="gbk")
        store = knowledge.KnowledgeStore(self.index_dir)
        store.refresh([str(self.docs)])
        hits = store.search("磷酸铁锂", dirs=[str(self.docs)])
        self.assertTrue(hits)
        self.assertIn("磷酸铁锂", hits[0]["text"])

    def test_docx_tables_are_indexed(self):
        docx_path = self.docs / "table.docx"
        try:
            import docx as docx_lib
            document = docx_lib.Document()
            document.add_paragraph("电池术语表如下。")
            table = document.add_table(rows=1, cols=2)
            table.rows[0].cells[0].text = "coulombic efficiency"
            table.rows[0].cells[1].text = "库仑效率"
            document.save(str(docx_path))
        except Exception as e:  # noqa: BLE001 — 环境缺依赖则跳过
            self.skipTest(f"无法构造 docx：{e}")
        store = knowledge.KnowledgeStore(self.index_dir)
        stats = store.refresh([str(self.docs)])
        self.assertGreaterEqual(stats["files"], 1)
        hits = store.search("库仑效率", dirs=[str(self.docs)])
        self.assertTrue(hits)

    def test_refresh_search_and_stats(self):
        self._write("battery.md",
                    "# SEI\n\nThe solid electrolyte interphase (SEI) grows on the anode.\n\n"
                    "Intercalation of lithium into graphite.")
        self._write("cooking.txt", "How to make pancakes with flour and milk.")
        store = knowledge.KnowledgeStore(self.index_dir)
        stats = store.refresh([str(self.docs)])
        self.assertEqual(stats["files"], 2)
        self.assertGreater(stats["chunks"], 1)

        hits = store.search("SEI intercalation", dirs=[str(self.docs)])
        self.assertTrue(hits)
        self.assertTrue(hits[0]["path"].endswith("battery.md"))
        self.assertIn("SEI", hits[0]["text"])
        # 目录过滤：另一个目录检索不到
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertEqual(store.search("pancakes", dirs=[str(other)]), [])
        self.assertEqual(store.search("pancakes", dirs=[str(self.docs)])[0]["path"],
                         str(self.docs / "cooking.txt"))
        self.assertEqual(store.stats(dirs=[str(self.docs)])["files"], 2)

    def test_incremental_update_and_removal(self):
        a = self._write("a.txt", "alpha content one")
        store = knowledge.KnowledgeStore(self.index_dir)
        store.refresh([str(self.docs)])
        a.write_text("alpha content one rewritten", encoding="utf-8")
        time.sleep(0.02)  # 保证 mtime 变化
        b = self._write("b.txt", "beta content two")
        stats = store.refresh([str(self.docs)])
        self.assertEqual(stats["parsed"], 2)  # a 重解析 + b 新解析
        self.assertIn("rewritten", store.search("rewritten", dirs=[str(self.docs)])[0]["text"])
        b.unlink()
        stats = store.refresh([str(self.docs)])
        self.assertEqual(stats["files"], 1)
        self.assertEqual(store.search("beta", dirs=[str(self.docs)]), [])

    def test_index_persists_across_instances(self):
        self._write("keep.txt", "persisted knowledge about cathode materials")
        knowledge.KnowledgeStore(self.index_dir).refresh([str(self.docs)])
        store2 = knowledge.KnowledgeStore(self.index_dir)
        self.assertEqual(store2.stats()["files"], 1)
        self.assertIn("cathode", store2.search("cathode")[0]["text"])

    def test_unreadable_files_are_skipped(self):
        self._write("bad.pdf", "这不是真正的 PDF 二进制内容")
        self._write("good.txt", "good text here")
        store = knowledge.KnowledgeStore(self.index_dir)
        stats = store.refresh([str(self.docs)])
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["files"], 1)

    def test_search_empty_query_and_index(self):
        store = knowledge.KnowledgeStore(self.index_dir)
        self.assertEqual(store.search(""), [])
        self.assertEqual(store.search("anything"), [])


class ContextGatingTests(unittest.TestCase):
    def test_context_for_gates_by_kind_and_flags(self):
        store = None
        dom = {"kb_enabled": False, "kb_dirs": ["D:/x"], "kb_for_translate": False}
        self.assertEqual(knowledge.context_for(store, dom, "explain", "t"), "")
        dom["kb_enabled"] = True
        self.assertEqual(knowledge.context_for(store, dom, "explain", "t"), "")  # 无 store
        dom["kb_dirs"] = []
        self.assertEqual(knowledge.context_for(None, dom, "explain", "t"), "")
        dom["kb_dirs"] = ["D:/x"]

        class FakeStore:
            def search(self, query, dirs=None, top_k=3):
                return [{"path": "D:/x/a.md", "text": "片段", "score": 2.0}]

        self.assertIn("片段", knowledge.context_for(FakeStore(), dom, "explain", "t"))
        self.assertEqual(knowledge.context_for(FakeStore(), dom, "translate", "t"), "")
        dom["kb_for_translate"] = True
        self.assertIn("片段", knowledge.context_for(FakeStore(), dom, "translate", "t"))
        self.assertEqual(knowledge.context_for(FakeStore(), dom, "chat", "t"), "")

    def test_format_context_budget(self):
        hits = [{"path": f"p{i}", "text": "x" * 1500} for i in range(3)]
        text = knowledge.format_context(hits, budget=2000)
        self.assertIn("用户知识库", text)
        self.assertLessEqual(len(text), 2000 + 200)  # 头部与来源行开销
        self.assertEqual(knowledge.format_context([]), "")


if __name__ == "__main__":
    unittest.main()
