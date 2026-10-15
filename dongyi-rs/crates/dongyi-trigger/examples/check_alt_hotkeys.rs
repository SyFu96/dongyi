//! 本机定向检查：短暂注册 Alt+E/Q/T，以 SendInput 验证系统消息、去重和首次绑定优先。
use std::{mem::size_of, time::{Duration, Instant}};
use dongyi_trigger::{parse_hotkey, start, TriggerEvent};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
    KEYEVENTF_KEYUP, KEYBD_EVENT_FLAGS, VIRTUAL_KEY,
};

fn key(vk: u16, up: bool) -> INPUT {
    INPUT { r#type: INPUT_KEYBOARD, Anonymous: INPUT_0 { ki: KEYBDINPUT {
        wVk: VIRTUAL_KEY(vk), dwFlags: if up { KEYEVENTF_KEYUP } else { KEYBD_EVENT_FLAGS(0) },
        ..Default::default()
    } } }
}

fn main() {
    assert!([0x10, 0x11, 0x12, 0x5b, 0x5c].iter().all(|vk| unsafe { GetAsyncKeyState(*vk) } >= 0),
        "Release modifier keys before running this check");
    let mut specs = vec![];
    for (kind, letter) in [("explain", "e"), ("input", "q"), ("translate", "t")] {
        specs.push(parse_hotkey(kind, &format!("<alt>+{letter}")).unwrap());
    }
    specs.push(parse_hotkey("duplicate", "<alt>+e").unwrap());
    let rx = start(specs);
    std::thread::sleep(Duration::from_millis(300));
    for (expected, vk) in [("explain", 0x45), ("input", 0x51), ("translate", 0x54)] {
        let keys = [key(0x12, false), key(vk, false), key(vk, false), key(vk, true), key(0x12, true)];
        assert_eq!(unsafe { SendInput(&keys, size_of::<INPUT>() as i32) }, keys.len() as u32);
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match rx.recv_timeout(deadline.saturating_duration_since(Instant::now())).unwrap() {
                TriggerEvent::Hotkey { kind } => { assert_eq!(kind, expected); break; }
                _ => continue,
            }
        }
        std::thread::sleep(Duration::from_millis(80));
        assert!(!rx.try_iter().any(|event| matches!(event, TriggerEvent::Hotkey { .. })), "Duplicate hotkey dispatch");
        println!("PASS: {expected}");
    }
}
