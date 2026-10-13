//! 懂译取词：UIA 读选中文本 + 受控剪贴板兜底。
//!
//! capture.py 的忠实移植，所有"坑注释"原样保留：
//! - 所有 UIA/剪贴板调用在常驻捕获线程内做，线程启动即 CoInitialize(MTA)。
//! - 静默（拖选）路径永不碰用户剪贴板；显式（热键）路径是用户明确动作，
//!   UIA 失败即走兜底，不受白名单限制。
//! - 兜底只在"可可靠还原"的剪贴板上操作（空/纯文本及其合成格式组合；
//!   含图片/文件/富格式直接跳过）；备份/还原用本线程临时创建的
//!   message-only owner 窗口——MS 文档明示 owner=NULL 时 SetClipboardData
//!   可能失败，绝不能 OpenClipboard(None) 后写剪贴板。
//! - 剪贴板序号是"复制是否成功"的唯一可信信号：备份序号必须**读取完成后**
//!   记录（读备份可能触发目标应用延迟渲染，序号会动）；读结果时的序号
//!   必须与观测到的那次变化一致，序号再变就放弃（内容可能已被他人改写）。
//! - 坐标一律屏幕物理像素（全局坐标系），与 Tauri PhysicalPosition 同系。

use std::ffi::c_void;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use log;
use serde::Serialize;
use windows::core::{w, Interface, PWSTR};
use windows::Win32::Foundation::{CloseHandle, GlobalFree, HANDLE, HGLOBAL, HWND};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED,
};
use windows::Win32::System::DataExchange::{
    CloseClipboard, EmptyClipboard, EnumClipboardFormats, GetClipboardData,
    GetClipboardSequenceNumber, IsClipboardFormatAvailable, OpenClipboard, SetClipboardData,
};
use windows::Win32::System::Memory::{
    GlobalAlloc, GlobalLock, GlobalSize, GlobalUnlock, GMEM_MOVEABLE,
};
use windows::Win32::System::Ole::{
    CF_UNICODETEXT, SafeArrayDestroy, SafeArrayGetElement, SafeArrayGetLBound, SafeArrayGetUBound,
};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_FORMAT, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationTextPattern, IUIAutomationTextRange,
    UIA_TextPatternId,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBD_EVENT_FLAGS, KEYBDINPUT,
    KEYEVENTF_KEYUP, VIRTUAL_KEY, VK_C, VK_CONTROL, VK_LWIN, VK_MENU, VK_RWIN, VK_SHIFT,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DestroyWindow, GetClassNameW, GetForegroundWindow, GetWindowThreadProcessId,
    HWND_MESSAGE, WINDOW_EX_STYLE, WINDOW_STYLE,
};

// ---------------------------------------------------------------- 数据结构

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
pub enum SelectionSource {
    #[serde(rename = "uia")]
    Uia,
    #[serde(rename = "clipboard")]
    Clipboard,
}

#[derive(Debug, Clone, Serialize)]
pub struct Selection {
    /// 非空、去首尾空白、超长已截断
    pub text: String,
    /// 选区包围盒 (l, t, w, h) 屏幕物理像素
    pub rect: Option<(i32, i32, i32, i32)>,
    pub source: SelectionSource,
    pub truncated: bool,
}

#[derive(Debug, Clone, Default)]
pub struct CaptureCfg {
    pub max_text_len: usize,
    pub clipboard_fallback: bool,
    pub clipboard_fallback_processes: Vec<String>,
    pub blacklist_processes: Vec<String>,
}

impl CaptureCfg {
    /// 从 config.json 的 Value 构建缺字段兜底。
    pub fn from_value(v: &serde_json::Value) -> Self {
        fn str_list(v: &serde_json::Value) -> Vec<String> {
            v.as_array()
                .map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_owned)).collect())
                .unwrap_or_default()
        }
        Self {
            max_text_len: v["max_text_len"].as_u64().unwrap_or(3000) as usize,
            clipboard_fallback: v["clipboard_fallback"].as_bool().unwrap_or(true),
            clipboard_fallback_processes: str_list(&v["clipboard_fallback_processes"]),
            blacklist_processes: str_list(&v["blacklist_processes"]),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Mode {
    /// 拖选路径：绝不碰剪贴板（除非白名单兜底）
    #[serde(rename = "silent")]
    Silent,
    /// 热键路径：UIA 失败即走剪贴板兜底（用户显式触发）
    #[serde(rename = "explicit")]
    Explicit,
}

// ---------------------------------------------------------------- COM 线程管理

/// 在当前线程初始化 COM（捕获线程启动时调用一次）。
/// 已在其它模式下初始化（RPC_E_CHANGED_MODE）也接受，Python 版同等宽容。
/// STA 与 Python 版（pythoncom.CoInitialize = APARTMENTTHREADED）一致；
/// Gate 试测反馈：VS Code（Electron/Chromium provider）在 MTA 下取词失败，
/// STA 为实测可行组合。
pub fn ensure_com() {
    let hr = unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED) };
    let _ = hr; // S_OK / S_FALSE / RPC_E_CHANGED_MODE 均继续
}

/// 创建 UIA 客户端（创建线程须已 ensure_com）。
pub fn create_automation() -> Option<IUIAutomation> {
    unsafe {
        CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()
    }
}

// ---------------------------------------------------------------- 进程/窗口信息

/// 窗口句柄 → 进程名（小写，含扩展名）。失败返回空串。
pub fn process_name_of_hwnd(hwnd: isize) -> String {
    if hwnd == 0 {
        return String::new();
    }
    unsafe {
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(HWND(hwnd as *mut _), Some(&mut pid));
        if pid == 0 {
            return String::new();
        }
        let h = match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            Ok(h) => h,
            Err(_) => return String::new(),
        };
        let mut buf = [0u16; 512];
        let mut size = buf.len() as u32;
        let name = QueryFullProcessImageNameW(h, PROCESS_NAME_FORMAT(0), PWSTR(buf.as_mut_ptr()), &mut size)
            .ok()
            .map(|_| String::from_utf16_lossy(&buf[..size as usize]));
        let _ = CloseHandle(h);
        name.map(|p| p.rsplit(['\\', '/']).next().unwrap_or("").to_lowercase())
            .unwrap_or_default()
    }
}

/// 当前前台窗口句柄（isize）；失败返回 None。
pub fn foreground_hwnd() -> Option<isize> {
    unsafe {
        let h = GetForegroundWindow();
        Some(h.0 as isize).filter(|&v| v != 0)
    }
}

/// 窗口类名；失败返回空串。
pub fn window_class(hwnd: isize) -> String {
    if hwnd == 0 {
        return String::new();
    }
    unsafe {
        let mut buf = [0u16; 256];
        let n = GetClassNameW(HWND(hwnd as *mut _), &mut buf);
        (n > 0).then(|| String::from_utf16_lossy(&buf[..n as usize])).unwrap_or_default()
    }
}

// 集成终端窗口类：Ctrl+C 可能是复制或中断信号，统一拦在白名单之外。
// VSCode 等 Electron 应用类名同为 Chrome_WidgetWin_1，无法按类区分编辑器
// 与集成终端——它们不在默认白名单里，用户手动加入即自担误发风险。
const TERMINAL_EXCLUDED_CLASSES: [&str; 3] = [
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "PseudoConsoleWindow",
];

// ---------------------------------------------------------------- UIA 取词

/// UIA 读焦点控件的选中文本；失败返回 None（COM 异常/无 TextPattern）。
/// 仅可在确保 COM 已初始化、且持有线程上调用。
pub fn uia_selection(automation: &IUIAutomation, max_text_len: usize) -> Option<Selection> {
    unsafe {
        let focused = automation.GetFocusedElement().ok()?;
        let unknown = focused.GetCurrentPattern(UIA_TextPatternId).ok()?;
        let pattern: IUIAutomationTextPattern = unknown.cast().ok()?;
        let ranges = pattern.GetSelection().ok()?;
        let n = ranges.Length().ok()?;
        for i in 0..n {
            let range: IUIAutomationTextRange = match ranges.GetElement(i).ok() {
                Some(r) => r,
                None => continue,
            };
            let text = match range.GetText(-1) {
                Ok(t) => t.to_string(),
                Err(_) => continue,
            };
            if text.trim().is_empty() {
                continue;
            }
            let raw_len = text.trim().chars().count();
            let truncated = raw_len > max_text_len;
            let mut text = text.trim().to_owned();
            if text.chars().count() > max_text_len {
                text = text.chars().take(max_text_len).collect();
            }
            // 拿不到包围盒不致命
            let rect = bounding_rect(&range);
            return Some(Selection { text, rect, source: SelectionSource::Uia, truncated });
        }
    }
    None
}

/// 取选区包围盒合并值 (l,t,w,h)；SAFEARRAY 是 VT_R8 的 [l,t,w,h]*n。
/// 空数组（LBound=0、UBound=-1）：i32 域判定后直接放弃选区——usize 先转的
/// 写法曾把 -1 变 usize::MAX 导致 `hi-lo+1` 溢出 panic，杀掉整个捕获线程
/// （表现为拖选/热键全部失效，输入翻译幸存）。
unsafe fn bounding_rect(range: &IUIAutomationTextRange) -> Option<(i32, i32, i32, i32)> {
    unsafe {
    let sa = range.GetBoundingRectangles().ok()?;
    let res = (|| {
        let lo = SafeArrayGetLBound(sa, 1).ok()?;
        let hi = SafeArrayGetUBound(sa, 1).ok()?;
        let count = elem_count(lo, hi)?;
        let mut vals = vec![0f64; count];
        for i in 0..count {
            let idx = [lo + i as i32];
            SafeArrayGetElement(sa, idx.as_ptr(), vals.get_mut(i).unwrap() as *mut f64 as *mut c_void).ok()?;
        }
        // 各行包围盒取并集（Python 版同样逻辑）
        let mut l = f64::MAX; let mut t = f64::MAX;
        let mut r = f64::MIN; let mut b = f64::MIN;
        for chunk in vals.chunks_exact(4) {
            l = l.min(chunk[0]); t = t.min(chunk[1]);
            r = r.max(chunk[0] + chunk[2]); b = b.max(chunk[1] + chunk[3]);
        }
        (r > l && b > t).then(|| (l as i32, t as i32, (r - l) as i32, (b - t) as i32))
    })();
    let _ = SafeArrayDestroy(sa);
    res
    }
}

/// 元素个数（每矩形 4 个 double）是 4 的倍数；空/异常长度直接判失败。
/// 全程 i32 运算，规避 usize 转换的 -1（空数组）放大。
fn elem_count(lo: i32, hi: i32) -> Option<usize> {
    if hi < lo {
        return None; // 含空数组（UBound=-1）
    }
    let n = (hi - lo + 1) as usize;
    (n % 4 == 0 && n >= 4).then_some(n)
}

// ---------------------------------------------------------------- 剪贴板兜底

/// 纯文本内容的合成格式组合：EnumClipboardFormats 对 CF_UNICODETEXT 通常还会
/// 列出系统合成的 CF_TEXT/CF_OEMTEXT/CF_LOCALE（MS "Clipboard Formats"），
/// 这些不算"另有格式"，允许静默兜底写入后按文本还原。
const TEXT_FORMAT_OK: [u32; 4] = [
    1,  // CF_TEXT（ANSI 合成）
    7,  // CF_OEMTEXT（OEM 合成）
    13, // CF_UNICODETEXT
    16, // CF_LOCALE（伴随 ANSI 文本出现）
];

fn clip_seq() -> u32 {
    unsafe { GetClipboardSequenceNumber() }
}

/// 读剪贴板 CF_UNICODETEXT（带开板重试）。max_seq 提供时把"序号核对+读数据"
/// 放进同一次开板窗口内：序号变化只说明"有人改过"，不证明就是目标应用响应
/// Ctrl+C，读到的内容必须与发键后观测到的那次序号一致才可信。
unsafe fn clipboard_text(max_seq: Option<u32>) -> Option<String> { unsafe {
    for _ in 0..3 {
        if OpenClipboard(None).is_err() {
            thread::sleep(Duration::from_millis(5)); // 剪贴板被占用
            continue;
        }
        let out = (|| {
            if let Some(seq) = max_seq {
                if clip_seq() != seq {
                    return None; // 序号又变了：读到的不一定是刚复制的那份，放弃
                }
            }
            if IsClipboardFormatAvailable(CF_UNICODETEXT.0 as u32).is_err() {
                return None;
            }
            let handle = GetClipboardData(CF_UNICODETEXT.0 as u32).ok()?;
            read_handle_text(handle)
        })();
        let _ = CloseClipboard();
        return out;
    }
    None
}}

/// HGLOBAL（UTF-16、NUL 结尾）→ String。
unsafe fn read_handle_text(handle: HANDLE) -> Option<String> { unsafe {
    let h = HGLOBAL(handle.0);
    let cap = GlobalSize(h) / 2; // 分配的字节数 / 2 = u16 数
    let ptr = GlobalLock(h) as *const u16;
    if ptr.is_null() {
        return None;
    }
    let mut len = 0usize;
    for i in 0..cap {
        if *ptr.add(i) == 0 {
            break;
        }
        len = i + 1;
    }
    let s = String::from_utf16_lossy(std::slice::from_raw_parts(ptr, len));
    let _ = GlobalUnlock(h);
    Some(s)
}}

/// 一次开板事务内的剪贴板备份快照。
#[derive(Debug, Clone)]
struct ClipSnapshot {
    /// 事务内记录的序号（后续读结果/还原的时效基准）
    seq: u32,
    /// 备份纯文本；"" = 空剪贴板（还原=清空）；None = 读取失败
    text: Option<String>,
    /// 空或纯文本合成组合 → 可可靠还原
    text_only: bool,
    /// False = 枚举/读取失败或剪贴板被占用（不该发键）
    ok: bool,
}

/// 同一 OpenClipboard 事务内：枚举格式 → 读纯文本 → 记录序号。
///
/// 序号必须在**读取完成后**（关板前）记录：读备份可能触发目标应用的延迟
/// 渲染（GetClipboardData → WM_RENDERFORMAT → SetClipboardData），期间序号
/// 递增；先记 seq 会把"渲染序号"误判为 Ctrl+C 的响应，把旧备份内容当选区。
/// 读取失败（异常/类型异常）→ ok=False，静默不发键。
unsafe fn clipboard_backup_snapshot() -> ClipSnapshot { unsafe {
    for _ in 0..3 {
        if OpenClipboard(None).is_err() {
            thread::sleep(Duration::from_millis(5));
            continue;
        }
        let out = (|| {
            let mut text_only = true;
            let mut fmt = 0u32;
            loop {
                fmt = EnumClipboardFormats(fmt);
                if fmt == 0 {
                    break; // 0 = 枚举结束
                }
                if !TEXT_FORMAT_OK.contains(&fmt) {
                    text_only = false;
                    break;
                }
            }
            // 空剪贴板：还原语义 = EmptyClipboard（还原为空）
            let mut text: Option<String> = Some(String::new());
            let mut ok = true;
            if IsClipboardFormatAvailable(CF_UNICODETEXT.0 as u32).is_ok() {
                let got = GetClipboardData(CF_UNICODETEXT.0 as u32)
                    .ok()
                    .and_then(|handle| read_handle_text(handle));
                match got {
                    Some(s) => text = Some(s),
                    None => {
                        ok = false;
                        text = None;
                    }
                }
            }
            let seq = clip_seq(); // 读取后、关板前：延迟渲染已使序号稳定
            ClipSnapshot { seq, text, text_only, ok }
        })();
        let _ = CloseClipboard();
        return out;
    }
    ClipSnapshot { seq: 0, text: None, text_only: false, ok: false } // 一直被占用
}}

/// 一个 KEYBDINPUT 键事件
fn key(vk: VIRTUAL_KEY, up: bool) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: if up { KEYEVENTF_KEYUP } else { KEYBD_EVENT_FLAGS(0) },
                time: 0,
                dwExtraInfo: 0,
            },
        },
    }
}

/// 用户此刻按住的修饰键（模拟前要临时释放，避免 Ctrl+C 被改写成 Ctrl+Shift+C 之类）
unsafe fn held_modifiers() -> Vec<VIRTUAL_KEY> { unsafe {
    let candidates = [VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN];
    candidates
        .iter()
        .filter(|vk| ((GetAsyncKeyState(vk.0 as i32) as u16) & 0x8000) != 0)
        .copied()
        .collect()
}}

/// SendInput 模拟 Ctrl+C：先临时释放用户按住的冲突修饰键，组合键发完再恢复。
unsafe fn send_ctrl_c() { unsafe {
    let held = held_modifiers();
    let mut items: Vec<INPUT> = Vec::new();
    items.extend(held.iter().map(|&vk| key(vk, true)));
    items.push(key(VK_CONTROL, false));
    items.push(key(VK_C, false));
    items.push(key(VK_C, true));
    items.push(key(VK_CONTROL, true));
    items.extend(held.iter().rev().map(|&vk| key(vk, false)));
    SendInput(&items, std::mem::size_of::<INPUT>() as i32);
}}

/// 临时 message-only owner 窗口（STATIC 系统类，HWND_MESSAGE 父级）。
///
/// 空/写回剪贴板事务（OpenClipboard+Empty+Set）须持非 NULL owner：MS
/// SetClipboardData 文档明示 NULL owner 时可能失败。生命周期由调用方
/// 管理：静默事务外层 finally 统一销毁；延迟还原线程自建自销。失败返回
/// None，调用方放弃写回。
unsafe fn clipboard_owner_hwnd() -> Option<HWND> { unsafe {
    CreateWindowExW(
        WINDOW_EX_STYLE(0),
        w!("STATIC"),
        w!("dongyi-clipboard"),
        WINDOW_STYLE(0),
        0, 0, 0, 0,
        Some(HWND_MESSAGE),
        None,
        None,
        None,
    )
    .ok()
}}

/// 持调用方的 owner HWND 写回备份；不管理 hwnd 生命周期。
///
/// - OpenClipboard(hwnd) 成功后核对序号 == expect_seq：不等则写回会清掉
///   用户新内容，跳过。
/// - text=None 跳过还原；"" = 只 Empty（还原为空）。
unsafe fn restore_clipboard_text_sync(hwnd: HWND, text: Option<&str>, expect_seq: u32) -> bool { unsafe {
    for _ in 0..3 {
        if OpenClipboard(Some(hwnd)).is_err() {
            thread::sleep(Duration::from_millis(5)); // 被其他程序占用
            continue;
        }
        let out = (|| {
            if clip_seq() != expect_seq {
                log::debug!("还原前剪贴板又被改动，跳过写回");
                return false;
            }
            let Some(t) = text else {
                log::debug!("无纯文本备份，跳过还原");
                return true;
            };
            if EmptyClipboard().is_err() {
                return false;
            }
            if t.is_empty() {
                return true;
            }
            // CF_UNICODETEXT：UTF-16 + NUL 结尾
            let bytes: Vec<u16> = t.encode_utf16().chain([0]).collect();
            let Ok(h) = GlobalAlloc(GMEM_MOVEABLE, bytes.len() * 2) else {
                return false;
            };
            let p = GlobalLock(h) as *mut u16;
            if p.is_null() {
                let _ = GlobalFree(Some(h));
                return false;
            }
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), p, bytes.len());
            let _ = GlobalUnlock(h);
            // 注意：SetClipboardData 成功后 hmem 所有权归剪贴板，不能 GlobalFree
            if SetClipboardData(CF_UNICODETEXT.0 as u32, Some(HANDLE(h.0))).is_err() {
                let _ = GlobalFree(Some(h));
                log::warn!("剪贴板写回失败");
                return false;
            }
            true
        })();
        let _ = CloseClipboard();
        return out;
    }
    log::warn!("剪贴板持续被占用，未还原备份");
    false
}}

/// 350ms 延迟还原：显式热键路径保留旧行为时序（不打断用户紧接着的粘贴）。
///
/// owner 在还原线程内创建、本线程销毁；创建失败直接放弃写回（绝不
/// OpenClipboard(NULL)+Empty——owner 为 NULL 时 SetClipboardData 可能失败）。
unsafe fn restore_clipboard_text_delayed(text: Option<String>, expect_seq: u32) { unsafe {
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(350));
        ensure_com(); // 独立线程剪贴板 API 本身无需 COM，保留对称
        let Some(hwnd) = clipboard_owner_hwnd() else {
            log::warn!("延迟还原：owner 创建失败，放弃写回");
            return;
        };
        restore_clipboard_text_sync(hwnd, text.as_deref(), expect_seq);
        let _ = DestroyWindow(hwnd);
    });
}}

/// 模拟 Ctrl+C → 读结果 → 还原备份。
///
/// silent=True（拖选自动）：owner 建不出、备份不可纯文本还原、still_valid
/// 复查失败——任一都不发键；还原同步（同一 owner，事务统一销毁）。
/// silent=False（显式热键）：保留旧行为——剪贴板内容类型不设限（富格式
/// 只还原纯文本部分），350ms 延迟还原、owner 由还原线程自建自销毁。
/// 终端类窗口两条路径都跳过。still_valid：发键前复查（最新 id + 目标窗口）；
/// silent 另要求当前序号==备份完成时的序号（备份后被他人改过则跳过）。
pub fn clipboard_selection(
    max_text_len: usize,
    silent: bool,
    still_valid: Option<&dyn Fn() -> bool>,
) -> Option<Selection> {
    unsafe {
        let cls = foreground_hwnd().map(window_class).unwrap_or_default();
        if TERMINAL_EXCLUDED_CLASSES.contains(&cls.as_str()) {
            log::debug!("终端类窗口 {}，跳过剪贴板兜底", if cls.is_empty() { "<未知>" } else { &cls });
            return None;
        }

        let owner = if silent { clipboard_owner_hwnd() } else { None };
        if silent && owner.is_none() {
            log::debug!("owner 窗口创建失败，跳过兜底");
            return None;
        }
        // 静默事务的 owner 生命周期统一归外层（延迟还原自建自销）
        let result = (|| {
            let snap = clipboard_backup_snapshot();
            if !snap.ok {
                // 快照失败（占用/枚举/读取失败）：seq 基线不可用，继续发键
                // 只会把旧内容误报成选区——两条路径一致 fail-close
                log::debug!("剪贴板快照失败，跳过兜底（不发键）");
                return None;
            }
            if silent && !snap.text_only {
                log::debug!("剪贴板含不可纯文本还原的格式，静默跳过兜底");
                return None;
            }
            if let Some(f) = still_valid {
                if !f() {
                    log::debug!("发键前复查失败（请求过期/切窗），跳过兜底");
                    return None;
                }
            }
            if silent && clip_seq() != snap.seq {
                // 备份关板后剪贴板已被他人改动：其变化会被下面的检测误判为
                // Ctrl+C 响应，直接跳过
                log::debug!("备份后剪贴板已变，跳过兜底");
                return None;
            }
            send_ctrl_c();

            // 轮询 GetClipboardSequenceNumber 10ms×300ms
            let deadline = Instant::now() + Duration::from_millis(300);
            let mut copied_seq = None;
            while Instant::now() < deadline {
                let seq_now = clip_seq();
                if seq_now != snap.seq {
                    copied_seq = Some(seq_now);
                    break;
                }
                thread::sleep(Duration::from_millis(10));
            }
            let Some(copied_seq) = copied_seq else {
                return None; // 未复制成功：剪贴板未变，无需还原
            };
            // 读结果与序号核对在同一开板窗口内
            let text = clipboard_text(Some(copied_seq));
            if silent {
                restore_clipboard_text_sync(owner.unwrap(), snap.text.as_deref(), copied_seq);
            } else {
                // ""（原剪贴板为空）→ None：显式路径跳过还原，保持旧行为
                let backup = match snap.text.as_deref() {
                    Some("") => None,
                    other => other.map(str::to_owned),
                };
                restore_clipboard_text_delayed(backup, copied_seq);
            }
            let text = text?;
            if text.trim().is_empty() {
                return None;
            }
            let raw_len = text.trim().chars().count();
            let truncated = raw_len > max_text_len;
            let mut text = text.trim().to_owned();
            if text.chars().count() > max_text_len {
                text = text.chars().take(max_text_len).collect();
            }
            Some(Selection { text, rect: None, source: SelectionSource::Clipboard, truncated })
        })();
        if let Some(hwnd) = owner {
            let _ = DestroyWindow(hwnd);
        }
        result
    }
}

// ---------------------------------------------------------------- 静默路径准入

/// 静默（拖选）路径是否允许自动剪贴板兜底，及不允许时的原因（供日志/测试）。
///
/// 自动兜底会向前台窗口模拟 Ctrl+C，误发面大：仅对受支持的阅读器进程
/// 白名单生效（默认 sioyek.exe，可在 clipboard_fallback_processes 增补）。
/// 黑名单进程与终端窗口类优先拒绝。要求 clipboard_fallback 总开关开启。
pub fn silent_fallback_ok(cfg: &CaptureCfg, fg_hwnd: Option<isize>) -> (bool, String) {
    if !cfg.clipboard_fallback {
        return (false, "disabled".into());
    }
    let Some(hwnd) = fg_hwnd.or_else(foreground_hwnd) else {
        return (false, "no-foreground".into());
    };
    let cls = window_class(hwnd);
    if TERMINAL_EXCLUDED_CLASSES.contains(&cls.as_str()) {
        return (false, format!("terminal:{cls}"));
    }
    let pname = process_name_of_hwnd(hwnd);
    if pname.is_empty() {
        return (false, "no-process-name".into());
    }
    if cfg.blacklist_processes.iter().any(|n| n.to_lowercase() == pname) {
        return (false, format!("blacklisted:{pname}"));
    }
    let allow: std::collections::HashSet<String> = cfg
        .clipboard_fallback_processes
        .iter()
        .map(|n| {
            let n = n.trim().to_lowercase();
            if n.contains('.') { n } else { format!("{n}.exe") } // 允许省略 .exe 后缀
        })
        .collect();
    if !allow.contains(&pname) {
        return (false, format!("not-whitelisted:{pname}"));
    }
    (true, pname)
}

/// 取选中文本（供测试脚本同步调用；应用内走 CaptureWorker）。
///
/// 先 UIA；失败后：
/// - Explicit：直接走剪贴板兜底（终端窗口类跳过）。不走白名单：热键是用户显式动作。
/// - Silent：兜底只对 silent_fallback_ok 放行。无 cfg 时禁用自动兜底。
pub fn get_selection(mode: Mode, cfg: &CaptureCfg) -> Option<Selection> {
    ensure_com();
    let automation = create_automation()?;
    if let Some(sel) = uia_selection(&automation, cfg.max_text_len) {
        return Some(sel);
    }
    match mode {
        Mode::Explicit => clipboard_selection(cfg.max_text_len, false, None),
        Mode::Silent => {
            let (ok, _) = silent_fallback_ok(cfg, None);
            if ok {
                clipboard_selection(cfg.max_text_len, true, None)
            } else {
                None
            }
        }
    }
}

// ---------------------------------------------------------------- 捕获线程

pub struct CaptureJob {
    pub id: u64,
    /// UI 会话代沟（orchestrator 分配：close/新提交使旧结果整体失效）
    pub epoch: u64,
    pub mode: Mode,
    /// 热键 kind（"translate"/"explain"/"input"）或 "icon"
    pub purpose: String,
    /// submit 时的鼠标物理坐标（fallback 定位用）
    pub phys: Option<(i32, i32)>,
    pub cfg: CaptureCfg,
    /// submit 时的前台窗口（防切窗身份复查用）
    pub target_hwnd: isize,
}

pub struct CaptureResult {
    pub job: CaptureJob,
    pub sel: Option<Selection>,
}

/// 常驻捕获线程：串行处理取词请求，主线程防抖到期后投递任务。
///
/// latest-id 机制：submit 时 req_id 递增；silent 请求在三个检查点被淘汰
/// （出队时、自动兜底发键前、投递前）——连拖多次/拖滚动条/切窗时旧请求
/// 自然过期，且不会把别的窗口的选区投给 GUI。
/// epoch 感知（Gate 回归 B4）：explicit 提交废止排队中的 silent（latest=MAX）；
/// silent/explicit 在 UIA、发键、投递前均与 UI 会话 epoch 复核。
pub struct CaptureWorker {
    tx: mpsc::Sender<Option<CaptureJob>>,
    next_id: AtomicU64,
    latest: std::sync::Arc<AtomicU64>,
}

impl CaptureWorker {
    pub fn start(
        emit: impl Fn(CaptureResult) + Send + Sync + 'static,
        ui_epoch: std::sync::Arc<AtomicU64>,
    ) -> Self {
        let (tx, rx) = mpsc::channel::<Option<CaptureJob>>();
        let latest = std::sync::Arc::new(AtomicU64::new(0));
        let latest_in = latest.clone();
        let ui_epoch_in = ui_epoch.clone();
        thread::Builder::new()
            .name("dongyi-capture".into())
            .spawn(move || worker_run(rx, latest_in, ui_epoch_in, emit))
            .expect("启动捕获线程失败");
        Self { tx, next_id: AtomicU64::new(0), latest }
    }

    /// 提交请求；返回分配到的 id。epoch 由编排层分配（消费侧复查用）。
    pub fn submit(
        &self,
        mode: Mode,
        purpose: &str,
        phys: Option<(i32, i32)>,
        cfg: CaptureCfg,
        epoch: u64,
    ) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed) + 1;
        if mode == Mode::Silent {
            // latest-id 淘汰只作用于 silent 路径；explicit 永远有效
            self.latest.store(id, Ordering::Relaxed);
        } else {
            // Gate 回归 B4：显式提交废止队列中的 silent（热键打断拖选候选）
            self.latest.store(u64::MAX, Ordering::Relaxed);
        }
        let _ = self.tx.send(Some(CaptureJob {
            id,
            epoch,
            mode,
            purpose: purpose.to_owned(),
            phys,
            cfg,
            target_hwnd: foreground_hwnd().unwrap_or(0),
        }));
        id
    }

    /// 通知线程结束。
    pub fn stop(&self) {
        let _ = self.tx.send(None);
    }
}

fn worker_run(
    rx: mpsc::Receiver<Option<CaptureJob>>,
    latest: std::sync::Arc<AtomicU64>,
    ui_epoch: std::sync::Arc<AtomicU64>,
    emit: impl Fn(CaptureResult),
) {
    ensure_com();
    let automation = create_automation();
    while let Ok(Some(job)) = rx.recv() {
        let out = match job.mode {
            Mode::Explicit => {
                // Gate 回归 B4：显式路径在 UIA 成功投递前同样核对
                // 前台窗口=submit 时的目标窗 + UI 会话 epoch 未变
                let target = job.target_hwnd;
                let still_valid = || {
                    job.epoch == ui_epoch.load(Ordering::Relaxed)
                        && foreground_hwnd().unwrap_or(0) == target
                };
                let sel = match automation
                    .as_ref()
                    .and_then(|a| uia_selection(a, job.cfg.max_text_len))
                {
                    Some(sel) if still_valid() => Some(sel),
                    Some(_) => None, // UIA 命中但请求已过期/切窗 → 不投递
                    None => {
                        let still: &dyn Fn() -> bool = &still_valid;
                        clipboard_selection(job.cfg.max_text_len, false, Some(still))
                    }
                };
                Some(sel)
            }
            Mode::Silent => {
                // 出队前已被更新的请求取代 → 不投递（emit=None）
                if job.id != latest.load(Ordering::Relaxed) {
                    None
                } else {
                    Some(capture_silent(&automation, &job, &latest, &ui_epoch))
                }
            }
        };
        if let Some(sel) = out {
            emit(CaptureResult { job, sel });
        }
    }
}

/// 拖选取词：UIA → 受限剪贴板兜底。
///
/// 目标窗口在 submit 时固定；任务全程在三处与当前最新 id + 前台窗口核对，
/// 过期/切窗一律放弃（不投递），黑名单命中仍投递 sel=None（旧行为：GUI
/// 收尾隐蔽浮标）。
fn capture_silent(
    automation: &Option<IUIAutomation>,
    job: &CaptureJob,
    latest: &AtomicU64,
    ui_epoch: &AtomicU64,
) -> Option<Selection> {
    let target = job.target_hwnd;
    let is_latest = || job.id == latest.load(Ordering::Relaxed);
    // Gate 回归 B4：三处核对统一含 epoch（关窗/新会话后排队任务彻底作废）
    let still_valid =
        || is_latest() && job.epoch == ui_epoch.load(Ordering::Relaxed) && foreground_hwnd().unwrap_or(0) == target;
    let pname = process_name_of_hwnd(target);
    if !pname.is_empty() && job.cfg.blacklist_processes.iter().any(|n| n.to_lowercase() == pname) {
        log::debug!("进程 {pname} 命中黑名单，跳过静默取词");
        return None;
    }
    if !still_valid() {
        log::debug!("请求已过期或前台切换，放弃静默取词");
        return None;
    }
    let sel = automation
        .as_ref()
        .and_then(|a| uia_selection(a, job.cfg.max_text_len));
    let sel = sel.or_else(|| {
        if !still_valid() {
            return None;
        }
        let (ok, _) = silent_fallback_ok(&job.cfg, Some(target));
        if ok {
            // still_valid 再交给 clipboard_selection 内部复查（发键前）
            let still: &dyn Fn() -> bool = &still_valid;
            clipboard_selection(job.cfg.max_text_len, true, Some(still))
        } else {
            None
        }
    });
    if !still_valid() {
        log::debug!("UIA 成功路径同样核对：失败/切窗的结果不投递");
        return None; // UIA 成功路径同样核对
    }
    sel
}

// ------------------------------------------------------------- 捕获链单测

#[cfg(test)]
mod tests {
    use super::elem_count;

    #[test]
    fn 空safearray的ubound负一不溢出() {
        // 回归：UBound=-1（空数组） Previous 实现 as usize 后 hi-lo+1 溢出 panic
        assert_eq!(elem_count(0, -1), None);
        assert_eq!(elem_count(0, 3), Some(4)); // 1 个矩形
        assert_eq!(elem_count(0, 7), Some(8)); // 2 个矩形
        assert_eq!(elem_count(2, 3), None); // 不足 4 元素
    }
}