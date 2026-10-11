# -*- coding: utf-8 -*-
"""知识库（RAG）测试：分词、分块、索引增量更新、BM25 检索与注入门控。"""

import os
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

    def test_search_consistent_under_concurrent_refresh(self):
        # M2 回归：refresh 与 search 并发时，评分与返回文本必须来自同一代索引。
        # 语料的词项和块数都随代变化：genA 含 alpha（1 块），genB 不含（2 块）。
        # 若出现"新统计+旧文本"的错配，会返回不含查询词 alpha 的片段 → 断言抓包。
        import threading

        known_texts: set[str] = set()
        gen_a = "shared alpha content " * 20                      # 1 块，含 alpha
        gen_b = "\n\n".join(["shared beta content " * 30,
                             "shared gamma content " * 30])       # 2 块，不含 alpha
        known_texts.add(gen_a.strip())
        known_texts.add(gen_b.strip())
        self._write("f0.txt", gen_a)
        self._write("f1.txt", "alpha alpha alpha")
        known_texts.add(("alpha alpha alpha").strip())
        store = knowledge.KnowledgeStore(self.index_dir)
        store.refresh([str(self.docs)])

        thread_errors: list[Exception] = []
        stop = threading.Event()
        refresh_count = {"n": 0}
        queries_started = threading.Event()

        def refresher() -> None:
            try:
                if not queries_started.wait(3):
                    return  # 查询未开始（异常情形）：由主线程的计数断言兜底
                n = 0
                while not stop.is_set():
                    text = gen_b if n % 2 == 0 else gen_a
                    (self.docs / "f0.txt").write_text(text, encoding="utf-8")
                    store.refresh([str(self.docs)])
                    refresh_count["n"] += 1
                    n += 1
            except Exception as e:  # noqa: BLE001 — 传回主线程断言
                thread_errors.append(e)

        thread = threading.Thread(target=refresher, daemon=True)
        thread.start()

        def run_queries() -> None:
            for _ in range(20):
                hits = store.search("alpha", dirs=[str(self.docs)])
                for hit in hits:
                    self.assertIn("alpha", hit["text"].lower(),
                                  f"返回了不含查询词的片段（评分与文本不同代）：{hit}")
                    self.assertIn(hit["text"], known_texts)

        try:
            run_queries()          # 第一批查询无条件执行（不可能零查询通过）
            queries_started.set()  # 屏障：刷新只在查询开始后才进行，保证交错
            base = refresh_count["n"]
            # 继续查询直到完成 ≥3 轮刷新：评分与文本的同代性在版本切换期间被反复检验
            deadline = time.time() + 3
            while refresh_count["n"] < base + 3 and time.time() < deadline:
                run_queries()
                time.sleep(0.001)
        finally:
            stop.set()
            thread.join(5)
        self.assertEqual(thread_errors, [])
        self.assertGreaterEqual(refresh_count["n"] - base, 3,
                                "查询期间未发生版本切换，交错断言无效")

    def test_old_version_index_is_discarded(self):
        # M7 回归：旧版本索引（可能含此后才被排除的敏感文件）整体废弃，不参与检索
        import json
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.index_dir / "index.json").write_text(json.dumps({
            "version": knowledge.KnowledgeStore.VERSION - 1,
            "files": {"C:/fake/config.json": {"mtime": 0, "size": 0, "chunks": 1}},
            "chunks": [{"path": "C:/fake/config.json",
                        "text": "cloud api_key FAKE-SECRET-KEY battery"}],
        }, ensure_ascii=False), encoding="utf-8")
        store = knowledge.KnowledgeStore(self.index_dir)
        self.assertEqual(store.search("FAKE-SECRET-KEY"), [])  # 刷新前也搜不到
        self.assertEqual(store.stats()["files"], 0)

    def test_chunk_total_cap_marks_incomplete_and_refills(self):
        # M10 回归：总额度对缓存复用同样生效；被截断的文件标记 complete=False，
        # 容量释放后（其他文件删除）下次刷新重新解析补齐
        from unittest.mock import patch
        big_a = "\n\n".join(["甲" * 300, "乙" * 300])  # 2 块
        big_b = "\n\n".join(["丙" * 300, "丁" * 300])  # 2 块
        self._write("a.txt", big_a)
        self._write("b.txt", big_b)
        with patch.object(knowledge, "MAX_TOTAL_CHUNKS", 3):
            store = knowledge.KnowledgeStore(self.index_dir)
            stats = store.refresh([str(self.docs)])
            self.assertEqual(stats["chunks"], 3)  # a 完整 2 块 + b 被截到 1 块
            self.assertFalse(store._files[knowledge._identity(str(self.docs / "b.txt"))]["complete"])
            # 无容量变化：b 重解析仍被截断
            store.refresh([str(self.docs)])
            self.assertFalse(store._files[knowledge._identity(str(self.docs / "b.txt"))]["complete"])
            (self.docs / "a.txt").unlink()  # 释放容量
            store.refresh([str(self.docs)])
            record = store._files[knowledge._identity(str(self.docs / "b.txt"))]
            self.assertTrue(record["complete"])
            self.assertEqual(record["chunks"], 2)
            self.assertIn("丁", store.search("丁丁", dirs=[str(self.docs)])[0]["text"])
            # 完整缓存被排序更靠前的新文件挤占：0.txt 先占 2 块额度，
            # b（完整缓存 2 块）只能保留 1 块 → complete=False，等待补齐
            self._write("0.txt", "\n\n".join(["戊" * 300, "己" * 300]))
            store.refresh([str(self.docs)])
            record = store._files[knowledge._identity(str(self.docs / "b.txt"))]
            self.assertFalse(record["complete"], "完整缓存被挤占后应标记不完整")
            self.assertEqual(record["chunks"], 1)
            (self.docs / "0.txt").unlink()  # 容量再释放
            store.refresh([str(self.docs)])
            record = store._files[knowledge._identity(str(self.docs / "b.txt"))]
            self.assertTrue(record["complete"])
            self.assertEqual(record["chunks"], 2)

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

    def test_alias_paths_cannot_bypass_exclusion_or_split_index(self):
        # Major 复审回归：短名/链接别名访问同一目录时——
        # ① 排除规则仍生效（config.json 不得借别名进索引）；
        # ② 别名扫描、真实路径过滤也能命中（目录归属按身份判断）；
        # ③ 同一文件经两种别名刷新只算一个，不产生重复条目。
        import _winapi

        secret = self._write("config.json", 'cloud api key SK-FAKE-ALIAS-KEY battery')
        alias = Path(self.tmp.name) / "docs_alias"
        try:
            _winapi.CreateJunction(str(self.docs), str(alias))
        except Exception as e:  # noqa: BLE001 — 非 NTFS/权限不足则跳过
            self.skipTest(f"无法创建 junction：{e}")
        self._write("keep.txt", "alpha corpus text")

        store = knowledge.KnowledgeStore(self.index_dir, exclude=[secret])
        store.refresh([str(alias)])  # 用别名目录扫描
        self.assertEqual(store.search("SK-FAKE-ALIAS-KEY"), [], "排除被别名绕过")

        store.refresh([str(self.docs)])  # 换真实路径再刷：应识别为同一批文件
        self.assertEqual(store.stats()["files"], 1)
        hits = store.search("alpha", dirs=[str(alias)])  # 反向：别名过滤也命中
        self.assertTrue(hits, "别名目录过滤与真实路径扫描身份不一致")

        # 同一次刷新同时传入真实与别名目录：身份去重，不得产生双份索引
        store.refresh([str(self.docs), str(alias)])
        self.assertEqual(store.stats()["files"], 1, "别名导致同一文件被重复索引")

    def test_join_identity_handles_drive_root(self):
        # Major 复审回归：盘符根目录的身份自带尾分隔符（"d:\\"），
        # 字符串拼接会产生 "d:\\name" 双分隔符，与规则侧 _identity 的
        # "d:\\name" 失配 → 根目录文件的排除失效。必须走 os.path.join。
        self.assertEqual(knowledge._join_identity("d:\\", "private.json"),
                         os.path.normcase("d:\\private.json"))
        self.assertEqual(knowledge._join_identity("c:\\users\\x", "f.txt"),
                         os.path.normcase("c:\\users\\x\\f.txt"))
        # 与 _identity 的口径一致（同一文件两条路径身份相等）
        real = Path(tempfile.mkdtemp()) / "root_file.json"
        real.write_text("x", encoding="utf-8")
        self.assertEqual(knowledge._join_identity(knowledge._identity(real.parent),
                                                  real.name),
                         knowledge._identity(real))

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

    def test_pdf_flate_filter_array_form_is_supported(self):
        # 合法形式 /Filter [/FlateDecode]（单元素数组）不得被当未知滤镜跳页
        import zlib
        from pypdf import PdfWriter
        from pypdf.generic import (ArrayObject, DictionaryObject, NameObject,
                                   NumberObject, StreamObject)

        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        page = writer.pages[0]
        content = b"BT /F1 12 Tf 10 10 Td (cathode flate array form) Tj ET"
        stream = StreamObject()
        stream[NameObject("/Filter")] = ArrayObject([NameObject("/FlateDecode")])
        stream[NameObject("/Length")] = NumberObject(len(zlib.compress(content)))
        stream._data = zlib.compress(content)
        page[NameObject("/Contents")] = writer._add_object(stream)
        font = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }))
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        path = self.docs / "array.pdf"
        with open(path, "wb") as fh:
            writer.write(fh)

        import pypdf
        reader = pypdf.PdfReader(str(path))
        decoded = knowledge._page_decoded_bytes(
            reader.pages[0], knowledge.MAX_PAGE_DECODED_BYTES)
        self.assertIsNotNone(decoded)
        self.assertGreater(decoded, 0)
        store = knowledge.KnowledgeStore(self.index_dir)
        store.refresh([str(self.docs)])
        hits = store.search("flate array form", dirs=[str(self.docs)])
        self.assertTrue(hits, "单元素 Flate 数组滤镜的页面被误跳过")

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
        # 统计由后台预热：GUI 线程的 search/stats 在就绪前返回空/0（M9 语义），
        # 轮询等待预热完成
        deadline = time.time() + 2
        while store2.stats()["files"] == 0 and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(store2.stats()["files"], 1)
        hits: list[dict] = []
        deadline = time.time() + 2
        while not hits and time.time() < deadline:
            hits = store2.search("cathode")
            time.sleep(0.02)
        self.assertIn("cathode", hits[0]["text"])

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
