//! Read-only UIA probe: no simulated keys, no clipboard access, no selected text logged.
use std::{thread, time::{Duration, Instant}};
use dongyi_capture::{create_automation, ensure_com, foreground_hwnd, process_name_of_hwnd, uia_selection};
use windows::{core::Interface, Win32::UI::Accessibility::{IUIAutomationTextPattern, UIA_TextPatternId}};

fn main() {
    ensure_com();
    let automation = create_automation().expect("UIA unavailable");
    let until = Instant::now() + Duration::from_secs(100);
    while Instant::now() < until {
        if foreground_hwnd().is_some_and(|h| process_name_of_hwnd(h) == "chrome.exe") {
            let start = Instant::now();
            unsafe {
                let mut node = automation.GetFocusedElement().ok();
                let walker = automation.ControlViewWalker().ok();
                for depth in 0..18 {
                    let Some(element) = node else { break };
                    let pattern = element.GetCurrentPattern(UIA_TextPatternId)
                        .and_then(|p| p.cast::<IUIAutomationTextPattern>());
                    let selection = pattern.and_then(|p| p.GetSelection()).and_then(|ranges| {
                        let mut lengths = Vec::new();
                        for i in 0..ranges.Length()? {
                            lengths.push(ranges.GetElement(i)?.GetText(-1)?.to_string().trim().chars().count());
                        }
                        Ok(lengths)
                    });
                    println!("depth={depth} type={:?} class={:?} selected_lengths={selection:?} elapsed_ms={}",
                        element.CurrentControlType(), element.CurrentClassName().map(|s| s.to_string()), start.elapsed().as_millis());
                    node = walker.as_ref().and_then(|w| w.GetParentElement(&element).ok());
                }
                let resolved = uia_selection(&automation, 3000);
                println!("resolved_selection_chars={:?} elapsed_ms={}", resolved.map(|s| s.text.chars().count()), start.elapsed().as_millis());
            }
        }
        thread::sleep(Duration::from_secs(2));
    }
}
