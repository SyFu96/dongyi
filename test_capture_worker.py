# -*- coding: utf-8 -*-
"""CaptureWorker 与剪贴板兜底路径的隔离回归。

外部依赖全部用进程内假体替换：UIA、前台句柄/进程名/窗口类、真实剪贴板、
owner 窗口生命周期——CI 与无桌面环境可重复运行，不触碰真实剪贴板。

判别旧代码的用例：静默兜底现在要求"白名单进程 + 请求未过期 + 前台窗口
未切换 + 备份可纯文本还原 + owner 可建"全满足；旧版本一律无条件发键。
"""

import threading
import time
import unittest
from unittest.mock import patch

import capture
from capture import CaptureWorker, Selection

CF_UNICODETEXT = 13
CF_DIB = 8          # 图片格式：不可纯文本还原
CF_TEXT = 1         # ANSI 合成
CF_OEMTEXT = 7      # OEM 合成
CF_LOCALE = 16      # locale 合成
FAKE_HWND = 4212    # owner 假句柄：只记录流转，不代表真实窗口


class _FakeTimer:
    """同步 Timer：restore 延迟线程在测试内立即可控执行，不留悬挂线程。"""

    def __init__(self, interval, function):
        self.function = function
        capture._FAKE_TIMER_SPAWNED.append(self)

    def start(self):
        self.function()


class _FakeClipboard:
    """进程内剪贴板假体：格式枚举/读写/序号可控，记录关键调用。"""

    # capture 通过 win32clipboard.<常数> 引用：假体必须提供同名属性
    CF_UNICODETEXT = CF_UNICODETEXT
    CF_TEXT = CF_TEXT
    CF_OEMTEXT = CF_OEMTEXT
    CF_LOCALE = CF_LOCALE

    def __init__(self):
        self.seq = 100
        self.formats: list[int] = []
        self.text: str | None = None
        self.opened_with: list = []   # OpenClipboard 收到的 hwnd（None=只读开板）
        self.emptied = 0
        self.written: list = []
        self.destroyed: list = []

    def EnumClipboardFormats(self, fmt: int) -> int:
        seq = self.formats
        if fmt == 0:
            return seq[0] if seq else 0
        i = seq.index(fmt) + 1
        return seq[i] if i < len(seq) else 0

    def IsClipboardFormatAvailable(self, fmt: int) -> bool:
        return fmt == CF_UNICODETEXT and CF_UNICODETEXT in self.formats

    def GetClipboardData(self, fmt: int):
        if fmt != CF_UNICODETEXT:
            raise OSError(fmt)
        return self.text

    def OpenClipboard(self, hwnd) -> None:
        self.opened_with.append(hwnd)

    def CloseClipboard(self) -> None:
        pass

    def EmptyClipboard(self) -> None:
        self.emptied += 1

    def SetClipboardData(self, fmt: int, value) -> None:
        assert fmt == CF_UNICODETEXT
        self.written.append(value)
        self.text = value
        self.formats = [CF_UNICODETEXT]


class _Harness(unittest.TestCase):
    """公共叠层：fake 剪贴板/序号/owner/DestroyWindow + 假前台窗口与 COM 隔离。

    foreground() 更新的是同一个假窗口状态（底层 win32gui 与 capture 内部
    辅助函数全走它），随时切换不叠加 patch 层。
    """

    def setUp(self):
        self.clip = _FakeClipboard()
        self.win = {"hwnd": 7, "cls": "NORMAL", "pname": "notepad.exe"}
        capture._FAKE_TIMER_SPAWNED = []
        for p in (
            patch.object(capture, "win32clipboard", self.clip),
            patch.object(capture, "_clip_seq", lambda: self.clip.seq),
            patch.object(capture, "_clipboard_owner_hwnd", lambda: FAKE_HWND),
            patch.object(capture.threading, "Timer", _FakeTimer),
            patch.object(capture, "ensure_com", lambda: None),
            patch.object(capture, "uninit_com", lambda: None),
            # 默认禁止真实键盘输入；需模拟目标应用响应的用例在内层以
            # side_effect 覆盖（如 app_copies）。
            patch.object(capture, "_send_ctrl_c"),
            # 剪贴板事务直接调用底层 API：一并隔离真实前台/终端窗口
            patch.object(capture.win32gui, "GetForegroundWindow",
                         lambda: self.win["hwnd"]),
            patch.object(capture.win32gui, "GetClassName",
                         lambda _h: self.win["cls"]),
            patch.object(capture, "_current_foreground_hwnd",
                         lambda: self.win["hwnd"]),
            patch.object(capture, "process_name_of_hwnd",
                         lambda _h: self.win["pname"]),
            patch.object(capture, "_window_class", lambda _h: self.win["cls"]),
            patch.object(capture.win32gui, "DestroyWindow",
                         side_effect=self.clip.destroyed.append),
        ):
            p.start()
            self.addCleanup(p.stop)

    def foreground(self, hwnd: int, pname: str, cls: str = "NORMAL") -> None:
        self.win.update(hwnd=hwnd, cls=cls, pname=pname)

    def app_copies(self, text: str):
        """目标应用响应 Ctrl+C：把新选区写进假剪贴板并推进序号。"""
        def react():
            self.clip.seq += 1
            self.clip.formats = [CF_UNICODETEXT]
            self.clip.text = text
        return react


class ClipboardSelectionUnitTests(_Harness):
    """_clipboard_selection 单函数级：剪贴板内容/序号/owner/还原语义。"""

    def test_silent_image_clipboard_never_sends_ctrl_c(self):
        # 含图片的复杂剪贴板不可纯文本还原：不发键（旧代码此处会发，判别性）
        self.clip.formats = [CF_UNICODETEXT, CF_DIB]
        with patch.object(capture, "_send_ctrl_c") as send:
            sel = capture._clipboard_selection(3000, silent=True)
        self.assertIsNone(sel)
        send.assert_not_called()
        self.assertEqual(self.clip.emptied, 0)
        self.assertEqual(self.clip.written, [])

    def test_silent_skips_restore_when_user_copied_during_read(self):
        # 序号只表示"有人改过"，不能证明是目标应用响应了 Ctrl+C：读取
        # 窗口内用户又复制了新内容时——结果作废、还原跳过、新内容保留。
        with patch.object(capture, "_send_ctrl_c", side_effect=self.app_copies("new")):
            real_read = capture._clipboard_text
            touched = []

            def read_with_user_copy(max_seq=None):
                if not touched:  # 只在首个读取窗口内模拟并发的用户复制
                    touched.append(1)
                    self.clip.seq += 1
                    self.clip.text = "user typed content"
                return real_read(max_seq=max_seq)

            with patch.object(capture, "_clipboard_text", side_effect=read_with_user_copy):
                sel = capture._clipboard_selection(3000, silent=True)
        self.assertIsNone(sel, "读到他人的数据不能当本次选区")
        self.assertEqual(self.clip.emptied, 0, "还原必须因序号不匹配跳过")
        self.assertEqual(self.clip.written, [], "不得覆盖用户新复制的内容")
        self.assertEqual(self.clip.destroyed, [FAKE_HWND], "owner 窗口须同线程销毁")

    def test_silent_owner_creation_failure_never_sends_keys(self):
        # owner 建不出来（还原无保障）：整个兜底放弃，绝不发键后才发现
        with patch.object(capture, "_clipboard_owner_hwnd", return_value=None), \
             patch.object(capture, "_send_ctrl_c") as send:
            sel = capture._clipboard_selection(3000, silent=True)
        self.assertIsNone(sel)
        send.assert_not_called()
        self.assertEqual(self.clip.destroyed, [])

    def test_send_ctrl_c_error_destroys_owner_and_propagates(self):
        # 复核复现：发键抛错不能吞掉继续返回 Selection，也不得泄漏 owner。
        # owner 销毁归事务外层 finally。
        with patch.object(capture, "_send_ctrl_c", side_effect=RuntimeError("sendinput failed")):
            with self.assertRaises(RuntimeError):
                capture._clipboard_selection(3000, silent=True)
        self.assertEqual(self.clip.destroyed, [FAKE_HWND], "owner 必须由外层 finally 清理")
        self.assertEqual(self.clip.emptied, 0)
        self.assertEqual(self.clip.written, [])

    def test_silent_seq_after_delayed_render_and_send_gate(self):
        # 复核复现（MS：延迟渲染完成时序号才递增）：备份读取触发目标应用
        # 渲染（GetClipboardData→SetClipboardData），序号 100→101。旧代码把
        # seq 记在读取前，渲染序号 101 被误判为 Ctrl+C 响应 → 恰把旧备份
        # 当成"选区"。修复口径：① seq 在读取完成（关板前）记录；② 发键前
        # 要求当前序号==snap.seq，备份后被他人改过则静默跳过。
        self.clip.formats = [CF_UNICODETEXT]
        self.clip.text = "旧备份"
        real_get = self.clip.GetClipboardData

        def delayed_render(_fmt):
            # 目标应用渲染完成（SetClipboardData）→ 序号递增；且只发生一次
            # （旧剪贴板实体化后，我们后续的读取不再触发渲染）
            self.clip.seq += 1
            self.clip.GetClipboardData = real_get
            return real_get(_fmt)

        self.clip.GetClipboardData = delayed_render
        with patch.object(capture, "_send_ctrl_c", side_effect=self.app_copies("选区文本")):
            sel = capture._clipboard_selection(3000, silent=True)
        self.assertIsNotNone(sel)
        self.assertEqual(sel.text, "选区文本", "渲染序号被误判：旧备份当成了选区")
        self.assertEqual(self.clip.written, ["旧备份"], "还原仍应正常")
        self.clip.GetClipboardData = real_get

        # 备份完成之后、发键之前剪贴板被改 → 序号 gate 拦截，不发键
        self.clip.seq = 200
        self.clip.text = "user chose"

        def user_touched_clipboard():
            self.clip.seq += 1  # 仍有效（id/窗口正确），只是剪贴板被改
            return True

        with patch.object(capture, "_send_ctrl_c") as send2:
            sel2 = capture._clipboard_selection(3000, silent=True,
                                                still_valid=user_touched_clipboard)
        self.assertIsNone(sel2)
        send2.assert_not_called()

    def test_silent_plain_text_roundtrip_restores_backup(self):
        self.clip.formats = [CF_UNICODETEXT]
        self.clip.text = "旧备份"
        with patch.object(capture, "_send_ctrl_c", side_effect=self.app_copies("选区文本")):
            sel = capture._clipboard_selection(3000, silent=True)
        self.assertIsNotNone(sel)
        self.assertEqual(sel.text, "选区文本")
        self.assertEqual(sel.source, "clipboard")
        self.assertIn(FAKE_HWND, self.clip.opened_with,
                      "还原必须持与备份同一 owner HWND（禁止 NULL-owner 写回）")
        self.assertEqual(self.clip.written, ["旧备份"])
        self.assertEqual(self.clip.text, "旧备份")
        self.assertEqual(self.clip.destroyed, [FAKE_HWND])

    def test_explicit_keeps_hotkey_even_with_image_clipboard(self):
        # 显式热键保留旧行为：快照成功但含富文本/图片等复杂格式时照发键
        # （快照失败/占用则 fail-close，见下一条测试）
        self.clip.formats = [CF_UNICODETEXT, CF_DIB]
        self.clip.text = ""  # 富格式主体之外的可读纯文本（快照成功）
        with patch.object(capture, "_send_ctrl_c", side_effect=self.app_copies("hot")):
            sel = capture._clipboard_selection(3000, silent=False)
        self.assertIsNotNone(sel)
        self.assertEqual(sel.text, "hot", "热键路径不得因复杂剪贴板失效")
        self.assertEqual(self.clip.emptied, 0)  # 无纯文本备份需还原（""=还原为空）

    def test_unreadable_clipboard_fail_close_for_both_paths(self):
        # 复核复现：快照失败（ok=False）时旧代码继续发键且快照 seq=0 →
        # 任何非 0 序号立即被误判为"复制成功"，返回旧剪贴板文本。修复：
        # 失败快照两路径均不发键、不返回内容，热键重试即可。
        broken = capture._ClipSnapshot(seq=0, text=None, text_only=False, ok=False)
        for silent in (False, True):
            with patch.object(capture, "_clipboard_backup_snapshot", return_value=broken), \
                 patch.object(capture, "_clip_seq", lambda: 100), \
                 patch.object(capture, "_clipboard_text", return_value="old"), \
                 patch.object(capture, "_send_ctrl_c") as send:
                sel = capture._clipboard_selection(3000, silent=silent)
            self.assertIsNone(sel, "fail-close：不得把旧内容当选区")
            send.assert_not_called()  # 旧代码此处会发键并误报（判别性断言）


class WorkerFlowTests(_Harness):
    """CaptureWorker 级：白名单/黑名单/时效/前台身份/锁约束。"""

    def setUp(self):
        super().setUp()
        self.results: list = []
        self.worker = CaptureWorker(
            {"clipboard_fallback": True,
             "clipboard_fallback_processes": ["sioyek.exe"]},
            emit_result=lambda payload: self.results.append(payload))
        self.worker.start()
        self.addCleanup(self._stop_worker)

    def _stop_worker(self):
        self.worker.stop()
        self.worker.join(timeout=5)

    def _processed(self, timeout: float = 3.0) -> None:
        """等 worker 清空当前队列：不依赖 emit 是否发生。"""
        deadline = time.time() + timeout
        while self.worker._q.unfinished_tasks and time.time() < deadline:
            time.sleep(0.01)

    def _submit_and_wait(self):
        self.worker.submit("silent", "icon", (0, 0), 3000)
        deadline = time.time() + 5
        while len(self.results) < 1 and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.results, "worker 未按时投递结果")
        return self.results[0]

    def test_silent_falls_back_for_whitelisted_reader(self):
        self.foreground(7, "sioyek.exe")
        with patch.object(capture, "_uia_selection", return_value=None), \
             patch.object(capture, "_clipboard_selection",
                          return_value=Selection(text="clip", source="clipboard")) as cb:
            payload = self._submit_and_wait()
        self.assertEqual(payload["sel"].text, "clip")
        cb.assert_called_once()

    def test_silent_not_whitelisted_never_touches_clipboard(self):
        # 拖选自动兜底只对白名单进程：其他应用一律不自动发键
        self.foreground(7, "notepad.exe")
        with patch.object(capture, "_uia_selection", return_value=None), \
             patch.object(capture, "_clipboard_selection") as cb:
            payload = self._submit_and_wait()
        self.assertIsNone(payload["sel"])
        cb.assert_not_called()  # 旧代码会无条件兜底（判别性断言）

    def test_silent_blacklisted_process_is_dropped_early(self):
        self.foreground(7, "doom.exe")
        self.worker._cfg["blacklist_processes"] = ["doom.exe"]
        with patch.object(capture, "_uia_selection") as uia, \
             patch.object(capture, "_clipboard_selection") as cb:
            payload = self._submit_and_wait()
        self.assertIsNone(payload["sel"])
        uia.assert_not_called()  # 黑名单优先：连 UIA 都不查
        cb.assert_not_called()

    def test_silent_expired_request_never_falls_back(self):
        # UIA 取词期间来了新请求：本次已过期——兜底发键前必须放弃。
        # 旧代码顺序是"先兜底、发键后才查 latest"，会照样发键（判别性）。
        self.foreground(7, "sioyek.exe")
        submitted = []

        def uia_expire(_max):
            if not submitted:
                submitted.append(1)
                self.worker.submit("silent", "icon", (1, 1), 3000)
            return None

        with patch.object(capture, "_uia_selection", side_effect=uia_expire), \
             patch.object(capture, "_clipboard_selection", return_value=None) as cb:
            stale_id = self.worker.submit("silent", "icon", (0, 0), 3000)
            deadline = time.time() + 5
            while len(self.results) < 1 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(self.results), 1, "过期请求不得投递")
        self.assertNotEqual(self.results[0]["req"]["id"], stale_id,
                            "投递的应是新请求而不是过期请求")
        cb.assert_called_once()  # 仅新（仍有效）那次兜底，过期那次未发键

    def test_silent_foreground_switch_never_falls_back(self):
        # UIA 期间用户切了前台窗口：既不向新窗口发键，也不投递旧结果
        self.foreground(7, "sioyek.exe")

        def uia_switch(_max):
            p = patch.object(capture, "_current_foreground_hwnd", lambda: 999)
            p.start()
            self.addCleanup(p.stop)
            return None

        with patch.object(capture, "_uia_selection", side_effect=uia_switch), \
             patch.object(capture, "_clipboard_selection", return_value=None) as cb:
            self.worker.submit("silent", "icon", (0, 0), 3000)
            self._processed()
        self.assertEqual(self.results, [], "切窗后的任务结果不得投递")
        cb.assert_not_called()

    def test_silent_uia_success_but_target_window_switched_never_emits(self):
        # 复核复现：UIA 成功路径同样要最终核对 当前前台 == submit 目标窗口；
        # 排队/取词期间切窗 → 旧结果不投递（旧代码 emit 仍 True，判别性）
        self.foreground(7, "sioyek.exe")

        def uia_success_after_switch(_max):
            p = patch.object(capture, "_current_foreground_hwnd", lambda: 8)
            p.start()
            self.addCleanup(p.stop)
            return Selection(text="stale", source="uia")

        with patch.object(capture, "_uia_selection",
                          side_effect=uia_success_after_switch), \
             patch.object(capture, "_clipboard_selection") as cb:
            self.worker.submit("silent", "icon", (0, 0), 3000)
            self._processed()
        self.assertEqual(self.results, [], "切窗后的 UIA 结果不得投递")
        cb.assert_not_called()

    def test_silent_send_recheck_gates_before_ctrl_c(self):
        # 复核要求：复查回调必须贴着发键（完成备份之后、SendInput 之前）
        self.foreground(7, "sioyek.exe")
        with patch.object(capture, "_uia_selection", return_value=None), \
             patch.object(capture, "_clipboard_selection",
                          return_value=Selection(text="x", source="clipboard")) as cb:
            self.worker.submit("silent", "icon", (0, 0), 3000)
            self._processed()
        cb.assert_called_once()
        self.assertIsNotNone(cb.call_args.kwargs.get("still_valid"),
                              "静默兜底必须传入发键前复查回调")

    def test_explicit_hotkey_always_falls_back_despite_whitelist(self):
        # 热键是用户显式触发：不走白名单（非白名单进程同样兜底）
        self.foreground(7, "chrome.exe")
        with patch.object(capture, "_uia_selection", return_value=None), \
             patch.object(capture, "_clipboard_selection",
                          return_value=Selection(text="hot", source="clipboard")) as cb:
            self.worker.submit("explicit", "translate", (0, 0), 3000)
            deadline = time.time() + 5
            while len(self.results) < 1 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(self.results[0]["sel"].text, "hot")
        cb.assert_called_once()

    def test_submit_not_blocked_during_clipboard_wait(self):
        # 锁约束回归：worker 确实进入耗时剪贴板分支期间（Event 确认后），
        # 第二次 GUI submit 仍毫秒级返回——锁绝不横跨取词等待。
        self.foreground(7, "sioyek.exe")
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def slow_clipboard(*_a, **_k):
            entered.set()
            release.wait(2)
            return None

        with patch.object(capture, "_uia_selection", return_value=None), \
             patch.object(capture, "_clipboard_selection", side_effect=slow_clipboard):
            self.worker.submit("silent", "icon", (0, 0), 3000)
            self.assertTrue(entered.wait(2), "worker 未真正进入剪贴板分支")
            t0 = time.perf_counter()
            self.worker.submit("silent", "icon", (0, 0), 3000)
            dt = time.perf_counter() - t0
            self.assertLess(dt, 0.1, f"submit 被耗时取词阻塞（{dt:.3f}s）")
            # 放行与后续两个任务的完成都必须在 scoped mock 内处理：
            # mock 卸载后走到真实 UIA 会触发 COM 错误（Can not load
            # UIAutomationCore），不允许把这段留到 mock 外。
            release.set()          # 已 set：第二个任务进入 slow_clipboard 立即通过
            self._processed()      # 等 job1/job2 都投递完成

    def test_restore_skips_write_when_seq_changes_after_open(self):
        # 锁内检查覆盖：OpenClipboard(hwnd) 成功之后、Empty/Set 之前用户又
        # 复制 → 不 Empty 不 Set（用户新内容必须原样保留）。旧实现把序号
        # 检查放在开板之前，此间隙会被穿透。
        self.foreground(7, "sioyek.exe")
        self.clip.text = ""
        real_open = self.clip.OpenClipboard

        def open_then_user_copy(hwnd):
            real_open(hwnd)  # 还原事务开板成功后、写回前注入用户复制
            if hwnd == FAKE_HWND:
                self.clip.seq += 1
                self.clip.text = "user brand-new copy"

        with patch.object(self.clip, "OpenClipboard", side_effect=open_then_user_copy), \
             patch.object(capture, "_send_ctrl_c", side_effect=self.app_copies("选区")):
            sel = capture._clipboard_selection(3000, silent=True)
        self.assertEqual(sel.text, "选区")
        self.assertEqual(self.clip.emptied, 0, "开板后序号已变：不得 EmptyClipboard")
        self.assertEqual(self.clip.written, [], "开板后序号已变：不得覆盖新内容")
        self.assertEqual(self.clip.text, "user brand-new copy")


if __name__ == "__main__":
    unittest.main()
