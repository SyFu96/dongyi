//! 诊断用：对前台 PdfCraft 走一次静默取词（拖选路径）。
//! 会发送 Ctrl+C 并还原剪贴板，只在测试窗口上运行；启动后 2 秒内切到目标窗口。
use dongyi_capture::{ensure_com, foreground_hwnd, get_selection, process_name_of_hwnd, CaptureCfg, Mode};
use std::thread;
use std::time::Duration;

fn main() {
    ensure_com();
    thread::sleep(Duration::from_secs(2));
    let fg = foreground_hwnd().unwrap_or(0);
    println!("foreground={}", process_name_of_hwnd(fg));
    let cfg = CaptureCfg {
        max_text_len: 3000,
        clipboard_fallback: true,
        clipboard_fallback_processes: vec!["pdfcraft.exe".into()],
        blacklist_processes: vec![],
    };
    match get_selection(Mode::Silent, &cfg) {
        Some(sel) => println!(
            "OK source={:?} chars={} text={:?}",
            sel.source,
            sel.text.chars().count(),
            sel.text
        ),
        None => println!("NONE"),
    }
}
