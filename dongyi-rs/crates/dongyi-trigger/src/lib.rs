//! 全局鼠标 + 键盘监听（trigger.py 的忠实移植）。
//!
//! 坑 4（钩子回调阻塞）：低级钩子回调在系统给的全局钩子链上执行，任何
//! 阻塞都会让**全系统**的鼠标/键盘变卡。回调内只把事件投进 channel，
//! 取词/HTTP/窗口操作全部由编排线程做。
//!
//! mouse 线程语义同 Python Monitor._on_click：
//! - 拖选：位移 ≥ 12 物理像素
//! - 双击/三击选词：距上次 < 400ms 且位移 < 6px
//! - 键盘：Esc 全局关闭；热键组合触发时用 GetAsyncKeyState 现场核对修饰键
//!   （状态机可能遗漏抬键事件，不能仅凭记忆把单个键当热键），并用
//!   "按下集合"压制按键自动重复；注入事件（我们自己模拟的 Ctrl+C）忽略。

use std::cell::RefCell;
use std::collections::HashSet;
use std::sync::mpsc;
use std::sync::Arc;
use std::thread;
use std::time::Instant;

use serde::Serialize;
use windows::Win32::Foundation::{HINSTANCE, LPARAM, LRESULT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, VIRTUAL_KEY, VK_CONTROL, VK_LWIN, VK_MENU, VK_RWIN, VK_SHIFT,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, GetMessageW, SetWindowsHookExW, UnhookWindowsHookEx, KBDLLHOOKSTRUCT,
    LLKHF_INJECTED, MSG, MSLLHOOKSTRUCT, WH_KEYBOARD_LL, WH_MOUSE_LL, WM_KEYDOWN, WM_KEYUP,
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP,
    WM_SYSKEYDOWN, WM_SYSKEYUP,
};

// ---------------------------------------------------------------- 事件类型

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type")]
pub enum TriggerEvent {
    /// 任何按键按下（用于点击弹窗/浮标外时收尾）
    MouseDown { phys: (i32, i32), button: String },
    /// 拖选/多击选词候选 → 编排层防抖后取词
    Attempt { action: AttemptAction, phys: (i32, i32) },
    /// 热键触发（kind: translate / explain / input）
    Hotkey { kind: String },
    /// Esc：关闭弹窗 + 隐藏浮标
    Esc,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum AttemptAction {
    #[serde(rename = "drag")]
    Drag,
    #[serde(rename = "multi")]
    Multi,
}

// ---------------------------------------------------------------- 参数常量

const DRAG_MIN_PX: i32 = 12; // 拖选判定：位移 ≥ 12 物理像素
const CLICK_MAX_PX: i32 = 6; // 多击判定：位移 < 6px
const MAX_CLICK_GAP_MS: u128 = 400; // 多击判定：距上次 < 400ms

const VK_ESCAPE: u32 = 0x1B;

// ---------------------------------------------------------------- 热键绑定

/// 热键规格：pynput 风格描述串 → 终键 + 修饰键集合
#[derive(Debug, Clone)]
pub struct HotkeySpec {
    pub kind: String,
    pub terminal_vk: u32,
    pub modifiers: Vec<&'static str>,
}

/// 解析 "<ctrl>+<alt>+<shift>+t" 风格描述；支持 ctrl/cmd/alt/shift
/// + 单个字母/数字 + F1~F12。坏描述返回 None（不弄挂整个监听）。
pub fn parse_hotkey(kind: &str, descr: &str) -> Option<HotkeySpec> {
    let mut final_vk: Option<u32> = None;
    let mut modifiers: Vec<&'static str> = Vec::new();
    for tok in descr.split('+') {
        let tok = tok.trim().trim_matches('<').trim_matches('>');
        match tok.to_lowercase().as_str() {
            "ctrl" => modifiers.push("ctrl"),
            "alt" => modifiers.push("alt"),
            "shift" => modifiers.push("shift"),
            "cmd" | "super" | "win" => modifiers.push("cmd"),
            s if s.len() >= 2
                && s.starts_with('f')
                && s[1..].bytes().all(|b| b.is_ascii_digit()) =>
            {
                let n: u32 = s[1..].parse().ok().filter(|n| (1..=24).contains(n))?;
                final_vk = Some(0x6F + n); // VK_F1 = 0x70
            }
            s if s.chars().count() == 1 => {
                let c = s.chars().next().unwrap().to_ascii_uppercase();
                let vk = if ('A'..='Z').contains(&c) || ('0'..='9').contains(&c) {
                    c as u32
                } else {
                    log::error!("[hotkey] 无法解析：{descr}（kind={kind}）");
                    return None;
                };
                final_vk = Some(vk);
            }
            _ => {
                log::error!("[hotkey] 无法解析：{descr}（kind={kind}）");
                return None;
            }
        }
    }
    Some(HotkeySpec {
        kind: kind.to_owned(),
        terminal_vk: final_vk?,
        modifiers,
    })
}

// ---------------------------------------------------------------- 启动

/// 启动监听线程；返回事件接收端。与 Python 版 Monitor.start 等价。
pub fn start(hotkeys: Vec<HotkeySpec>) -> mpsc::Receiver<TriggerEvent> {
    let (tx, rx) = mpsc::channel::<TriggerEvent>();
    let specs = Arc::new(hotkeys);
    thread::Builder::new()
        .name("dongyi-hooks".into())
        .spawn(move || pump(tx, specs))
        .expect("启动钩子线程失败");
    rx
}

// ---------------------------------------------------------------- 线程状态

struct HookState {
    tx: mpsc::Sender<TriggerEvent>,
    specs: Arc<Vec<HotkeySpec>>,
    // 拖选/多击状态机
    down_pos: Option<(i32, i32)>,
    up_pos: Option<(i32, i32)>,
    up_t: Option<Instant>,
    // 按键自动重复压制（按下的 vk 集合）
    keys_down: HashSet<u32>,
}

thread_local! {
    /// 钩子回调只在本线程触发，状态放 thread_local，无跨线程竞争
    static STATE: RefCell<Option<HookState>> = const { RefCell::new(None) };
}

/// 钩子线程：装钩子 → 消息泵。
fn pump(tx: mpsc::Sender<TriggerEvent>, specs: Arc<Vec<HotkeySpec>>) {
    STATE.with(|s| {
        *s.borrow_mut() = Some(HookState {
            tx,
            specs,
            down_pos: None,
            up_pos: None,
            up_t: None,
            keys_down: HashSet::new(),
        });
    });

    unsafe {
        let hmod = GetModuleHandleW(None).ok().map(|m| HINSTANCE(m.0));
        let mouse = SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_proc), hmod, 0);
        if mouse.is_err() {
            log::error!("鼠标钩子安装失败");
        }
        let keyboard = SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard_proc), hmod, 0);
        if keyboard.is_err() {
            log::error!("键盘钩子安装失败");
        }

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {}

        if let Ok(h) = mouse {
            let _ = UnhookWindowsHookEx(h);
        }
        if let Ok(h) = keyboard {
            let _ = UnhookWindowsHookEx(h);
        }
    }
}

// ---------------------------------------------------------------- 鼠标钩子

unsafe extern "system" fn mouse_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code >= 0 {
        unsafe {
            let msg = wparam.0 as u32;
            let ms = *(lparam.0 as *const MSLLHOOKSTRUCT);
            let phys = (ms.pt.x, ms.pt.y);
            let button: &'static str = match msg {
                m if m == WM_LBUTTONDOWN || m == WM_LBUTTONUP => "left",
                m if m == WM_RBUTTONDOWN || m == WM_RBUTTONUP => "right",
                m if m == WM_MBUTTONDOWN || m == WM_MBUTTONUP => "middle",
                _ => "",
            };
            let pressed =
                msg == WM_LBUTTONDOWN || msg == WM_RBUTTONDOWN || msg == WM_MBUTTONDOWN;
            STATE.with(|s| {
                let mut guard = s.borrow_mut();
                let Some(st) = guard.as_mut() else { return };
                let tx = st.tx.clone();
                if !button.is_empty() && pressed {
                    // 任何按键按下都通知编排层（用于关闭弹窗/浮标）
                    let _ = tx.send(TriggerEvent::MouseDown { phys, button: button.to_owned() });
                }
                if button != "left" {
                    return;
                }
                let now = Instant::now();
                if pressed {
                    // 多击：距上次抬起 <400ms 且位移 <6px
                    if let (Some(up), Some(t)) = (st.up_pos, st.up_t) {
                        if now.duration_since(t).as_millis() <= MAX_CLICK_GAP_MS
                            && dist(up, phys) <= CLICK_MAX_PX as f64
                        {
                            let _ = tx.send(TriggerEvent::Attempt {
                                action: AttemptAction::Multi,
                                phys,
                            });
                        }
                    }
                    st.down_pos = Some(phys);
                } else {
                    st.up_pos = Some(phys);
                    st.up_t = Some(now);
                    if let Some(down) = st.down_pos {
                        if dist(down, phys) >= DRAG_MIN_PX as f64 {
                            let _ = tx.send(TriggerEvent::Attempt {
                                action: AttemptAction::Drag,
                                phys,
                            });
                        }
                    }
                    st.down_pos = None;
                }
            });
        }
    }
    unsafe { CallNextHookEx(None, code, wparam, lparam) }
}

// ---------------------------------------------------------------- 键盘钩子

unsafe extern "system" fn keyboard_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code >= 0 {
        unsafe {
            let msg = wparam.0 as u32;
            let kb = *(lparam.0 as *const KBDLLHOOKSTRUCT);
            STATE.with(|s| {
                let mut guard = s.borrow_mut();
                let Some(st) = guard.as_mut() else { return };
                let tx = st.tx.clone();
                if kb.flags.contains(LLKHF_INJECTED) {
                    // 注入事件（我们自己模拟的 Ctrl+C）被热键逻辑忽略
                    return;
                }
                let vk = kb.vkCode;
                let down_msg = msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN;
                let up_msg = msg == WM_KEYUP || msg == WM_SYSKEYUP;
                if down_msg && st.keys_down.insert(vk) {
                    if vk == VK_ESCAPE {
                        let _ = tx.send(TriggerEvent::Esc);
                    }
                    for spec in st.specs.iter() {
                        if spec.terminal_vk == vk && all_modifiers_down(&spec.modifiers) {
                            let _ = tx.send(TriggerEvent::Hotkey { kind: spec.kind.clone() });
                            break; // 单键至多命中一个绑定（配置若重复，首个优先）
                        }
                    }
                } else if up_msg {
                    st.keys_down.remove(&vk);
                }
            });
        }
    }
    unsafe { CallNextHookEx(None, code, wparam, lparam) }
}

/// 现场核对修饰键真实按下状态（不信任状态机的记忆）
fn all_modifiers_down(names: &[&str]) -> bool {
    names.iter().all(|n| match *n {
        "ctrl" => down(VK_CONTROL),
        "alt" => down(VK_MENU),
        "shift" => down(VK_SHIFT),
        "cmd" => down(VK_LWIN) || down(VK_RWIN),
        _ => false,
    })
}

fn down(vk: VIRTUAL_KEY) -> bool {
    unsafe { ((GetAsyncKeyState(vk.0 as i32) as u16) & 0x8000) != 0 }
}

/// 多击/拖选位移（物理像素；i64 防跨屏大坐标平方溢出）
fn dist(a: (i32, i32), b: (i32, i32)) -> f64 {
    let dx = (a.0 - b.0) as f64;
    let dy = (a.1 - b.1) as f64;
    (dx * dx + dy * dy).sqrt()
}
