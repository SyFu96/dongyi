// 懂译 Rust 版壳层：托盘 + 弹窗/设置/浮标三窗 + 配置 IPC + 编排。
//
// 窗口模型（对应 Python 版 popup.py）：
// - popup：无边框、透明、置顶、不抢焦点（focusable=false）、跳过任务栏，
//   进入追问/输入翻译时再动态 set_focusable(true)（P3/P4 接入）。
// - settings：普通可聚焦窗口（P4 改为 ArtCraft 风无边框）。
// - icon：24px 无边框浮标，取词成功才显示（防误触核心）。
// 三窗共用同一前端，靠 location hash 区分视图。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod orchestrator;

use serde_json::Value;
use tauri::{
    AppHandle, Emitter, Manager, State, WindowEvent,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    webview::WebviewWindowBuilder,
};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_single_instance::init as single_instance;

/// 共享配置（ orchestrator 读同一份）
pub type SharedCfg = std::sync::Mutex<Value>;

pub const POPUP_LABEL: &str = "popup";
pub const SETTINGS_LABEL: &str = "settings";
pub const ICON_LABEL: &str = "icon";

#[tauri::command]
fn get_config(cfg: State<'_, SharedCfg>) -> Value {
    cfg.lock().unwrap().clone()
}

#[tauri::command]
async fn local_models(state: tauri::State<'_, SharedCfg>) -> Result<Vec<String>, String> {
    // Gate N4：普通同步命令默认跑在主线程，blocking HTTP 会卡 UI——
    // async 命令 + spawn_blocking，门内只短锁拷 base_url（有引用参数则必返 Result）
    let base = {
        let guard = state.lock().unwrap();
        guard
            .get("base_url")
            .and_then(|v| v.as_str())
            .unwrap_or("http://localhost:11434")
            .to_owned()
    };
    tauri::async_runtime::spawn_blocking(move || dongyi_llm::ollama_models(&base))
        .await
        .map_err(|e| e.to_string())
}

/// P4 设定保存（Gate N2）：不改"整份快照替换"，改为**差异路径写入**——
/// 锁内基于当前内存（=最近磁盘真值）按 path 应用设置页修改，未知/新字段
/// 永不丢失；成功才发布内存并广播。
#[derive(serde::Deserialize)]
struct ConfigPatch {
    path: Vec<String>,
    value: Value,
}

#[tauri::command]
fn save_config_paths(
    app: AppHandle,
    entries: Vec<ConfigPatch>,
    state: State<'_, SharedCfg>,
) -> Result<(), String> {
    let mut guard = state.lock().unwrap();
    let mut merged = guard.clone();
    eprintln!("[orch] save_config_paths entries={}", entries.len());
    for entry in &entries {
        let path = &entry.path;
        eprintln!("[orch] save path={}", path.join("."));
        if path.is_empty() {
            return Err("空路径".into());
        }
        let mut node = &mut merged;
        for seg in &path[..path.len() - 1] {
            node = &mut node[seg]; // serde_json IndexMut 自动建缺失父级
        }
        if entry.value.is_null() {
            // P5：null = 删除该键（领域删除等场景）
            if let Some(obj) = node.as_object_mut() {
                obj.remove(path.last().unwrap());
            }
        } else {
            node[path.last().unwrap()] = entry.value.clone();
        }
    }
    dongyi_core::save_config(&merged).map_err(|e| e.to_string())?;
    *guard = merged;
    drop(guard);
    // P4：跨窗口广播（设置页改完，前端 chip/主题即时刷新）。
    // kind 用空串：provider-chip 监听按 kind 过滤不会误触发
    let theme = state.lock().unwrap().get("theme").cloned().unwrap_or_default();
    let _ = app.emit(
        "config:updated",
        serde_json::json!({ "kind": "", "provider": "", "theme": theme }),
    );
    // P5：领域/kb_dirs 可能变化 → 编排层核对知识库刷新
    send_orchestrator_ev(&app, orchestrator::AppEvent::KbCheck);
    Ok(())
}

fn send_orchestrator(app: &AppHandle, ev: orchestrator::AppEvent) {
    if let Some(bridge) = app.try_state::<orchestrator::Bridge>() {
        let _ = bridge.0.send(ev);
    }
}

/// 浮标「译」被点击
#[tauri::command]
fn icon_clicked(app: AppHandle) -> Result<(), String> {
    send_orchestrator(&app, orchestrator::AppEvent::IconClicked);
    Ok(())
}

/// 弹出弹窗（不抢焦点）：隐藏→显示即可，保持 always-on-top。
#[tauri::command]
fn show_popup(app: AppHandle) -> Result<(), String> {
    let win = app
        .get_webview_window(POPUP_LABEL)
        .ok_or("popup 窗口不存在")?;
    win.show().map_err(|e| {
        eprintln!("[popup] show 失败: {e}");
        e.to_string()
    })
}

#[tauri::command]
fn hide_popup(app: AppHandle) -> Result<(), String> {
    // Gate P3-B2：隐藏 = 关窗入口，必须经过编排（断流/复位），不许绕过
    send_orchestrator(&app, orchestrator::AppEvent::Close);
    Ok(())
}

/// 打开设置窗（P5 修复）：
/// - 保持同步函数：托盘菜单从 Rust 内部直接调用，async 函数不 await 不会执行
/// - 去掉 center()（实测卡死主线程）；每次显示前强制恢复创建尺寸（曾变 131x36 炁态）
#[tauri::command]
fn show_settings(app: AppHandle) -> Result<(), String> {
    eprintln!("[orch] show_settings called");
    let win = app
        .get_webview_window(SETTINGS_LABEL)
        .ok_or("settings 窗口不存在")?;
    let _ = win.set_size(tauri::LogicalSize::new(820.0, 620.0));
    win.show().map_err(|e| e.to_string())?;
    win.set_focus().map_err(|e| e.to_string())
}

/// 设置窗关闭按钮（×）：隐藏而非销毁（配置仍留内存，下次秒开）。
/// 走 Rust 路径——Web 端 window API 需要 capabilities 许可，不必为这一处放行。
#[tauri::command]
fn hide_settings(app: AppHandle) {
    eprintln!("[orch] hide_settings called");
    if let Some(win) = app.get_webview_window(SETTINGS_LABEL) {
        let _ = win.hide();
    }
}

// ---- P3：LLM 相关命令（统一经 Bridge 转发编排线程，保证事件顺序） ----

fn send_orchestrator_ev(app: &AppHandle, ev: orchestrator::AppEvent) {
    send_orchestrator(app, ev);
}

#[tauri::command]
fn activate_tab(app: AppHandle, kind: String) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::Tab { kind });
}

#[tauri::command]
fn chat_question(app: AppHandle, question: String, translation: String, explanation: String) {
    send_orchestrator_ev(
        &app,
        orchestrator::AppEvent::ChatAsk { question, translation, explanation },
    );
}

#[tauri::command]
fn input_translate(app: AppHandle, text: String, target: Option<String>) {
    send_orchestrator_ev(
        &app,
        orchestrator::AppEvent::InputAsk { text, target: target.unwrap_or_default() },
    );
}

/// P5：弹窗「存为记忆」（translation 为前端校对框的最终译文，可空）
#[tauri::command]
fn tm_save(app: AppHandle, kind: String, translation: Option<String>) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::TmSave { kind, translation });
}

/// P5：切换激活学科（编排线程校验+落盘+广播；下次请求即生效）
#[tauri::command]
fn set_domain(app: AppHandle, id: String) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::SetDomain { id });
}

#[tauri::command]
fn llm_retry(app: AppHandle, kind: String) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::Retry { kind });
}

#[tauri::command]
fn llm_stop(app: AppHandle, kind: String) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::Stop { kind });
}

#[tauri::command]
fn set_input_provider(app: AppHandle, provider: String) {
    // 兼容旧名：input kind 的后端切换
    send_orchestrator_ev(&app, orchestrator::AppEvent::KindProvider { kind: "input".into(), provider });
}

/// 追问/输入统一的 kind 后端切换
#[tauri::command]
fn set_kind_provider(app: AppHandle, kind: String, provider: String) {
    send_orchestrator_ev(&app, orchestrator::AppEvent::KindProvider { kind, provider });
}

/// 置顶开关：置顶后 Esc/点外不关闭弹窗（Python popup.is_pinned 同款）。
#[tauri::command]
fn set_popup_pinned(app: AppHandle, on: bool) -> Result<(), String> {
    send_orchestrator_ev(&app, orchestrator::AppEvent::Pin { on });
    Ok(())
}

pub fn run() {
    // 启动计时（验收口径：到托盘/编排就绪）——进程内起点，setup 末尾打印
    let t0 = std::time::Instant::now();
    // 诊断日志：把 stderr 指到 %APPDATA%\dongyi\app.log（release 无控制台，
    // 无此步用户拿不到任何诊断信息——复审 M3 要求"可操作的日志位置"）
    redirect_stderr_to_log();
    let cfg = dongyi_core::load_config();

    tauri::Builder::default()
        .manage(std::sync::Mutex::new(cfg))
        .plugin(single_instance(|app, _args, _cwd| {
            // 二次启动：把已有实例的弹窗带出来，与 Python 版 SingleInstance 行为一致
            if let Some(win) = app.get_webview_window(POPUP_LABEL) {
                let _ = win.show();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            get_config,
            save_config_paths,
            show_popup,
            hide_popup,
            show_settings,
            hide_settings,
            local_models,
            icon_clicked,
            activate_tab,
            chat_question,
            input_translate,
            tm_save,
            set_domain,
            llm_retry,
            llm_stop,
            set_input_provider,
            set_kind_provider,
            set_popup_pinned,
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            build_tray(&handle)?;

            // 弹窗：460×420 逻辑像素（读配置），无边框透明、不抢焦点、初始隐藏
            let (w, h) = popup_size(&app.state::<SharedCfg>().lock().unwrap());
            let popup = WebviewWindowBuilder::new(
                app,
                POPUP_LABEL,
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("懂译")
            .inner_size(w as f64, h as f64)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .focusable(false)
            .focused(false)
            .visible(false)
            // Python 版有 QSizeGrip（"拖动右下角调整大小"）；无框窗口的
            // 原生边框缩放由 Tao 处理，弹窗可拉伸（P2 测试反馈修复）
            .resizable(true)
            .min_inner_size(380.0, 300.0)
            .build()?;
            // 点外部隐藏：Blur 事件在不抢焦点窗口上不可靠，改由编排层的
            // mouse-down 判定完成（坑 8 的 Rust 版处理），这里保留事件占位。
            let _ = popup.on_window_event(move |e| {
                if let WindowEvent::Focused(false) = e {}
            });

            // 设置窗：ArtCraft 风（P4）：无边框 + 前端自绘标题栏（拖拽区），
            // 可聚焦可输入；初始隐藏，托盘/隐私菜单呼出
            WebviewWindowBuilder::new(
                app,
                SETTINGS_LABEL,
                tauri::WebviewUrl::App("index.html#view=settings".into()),
            )
            .title("懂译 · 设置")
            .inner_size(820.0, 620.0)
            .decorations(false)
            .visible(false)
            .build()?;

            // 浮标：24px 无边框透明小窗，不抢焦点；取词成功才显示
            WebviewWindowBuilder::new(
                app,
                ICON_LABEL,
                tauri::WebviewUrl::App("index.html#view=icon".into()),
            )
            .title("懂译 · 浮标")
            .inner_size(24.0, 24.0)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .focusable(false)
            .focused(false)
            .visible(false)
            .resizable(false)
            .build()?;

            // 编排：钩子 + 捕获线程 + 防抖
            let cfg = handle.state::<SharedCfg>().lock().unwrap().clone();
            orchestrator::start(handle, cfg);

            // 验收口径：托盘/三窗/编排全部就绪的启动耗时（stderr 可查）
            eprintln!("[boot] ready in {}ms", t0.elapsed().as_millis());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("懂译启动失败");
}

/// 把本进程 stderr 重定向到 %APPDATA%\dongyi\app.log（append）。
/// release 版 `windows_subsystem = "windows"` 无控制台，不做此步所有 eprintln
/// 诊断都会丢失（复审 M3：用户需要可操作的日志位置）。
fn redirect_stderr_to_log() {
    use std::os::windows::io::AsRawHandle;
    let path = dongyi_core::data_dir().join("app.log");
    let Ok(file) = std::fs::OpenOptions::new().create(true).append(true).open(&path) else {
        return;
    };
    let handle = file.as_raw_handle();
    unsafe {
        let h = windows::Win32::Foundation::HANDLE(handle as *mut std::ffi::c_void);
        if windows::Win32::System::Console::SetStdHandle(
            windows::Win32::System::Console::STD_ERROR_HANDLE,
            h,
        )
        .is_err()
        {
            return; // 失败则保持原 stderr
        }
    }
    std::mem::forget(file); // 句柄已交给进程，防 drop 关闭
}

fn popup_size(cfg: &Value) -> (u32, u32) {    let w = cfg["popup"]["width"].as_u64().unwrap_or(460) as u32;
    let h = cfg["popup"]["height"].as_u64().unwrap_or(420) as u32;
    (w, h)
}

/// 托盘：左键切换弹窗；菜单 = 弹窗 / 设置 / 退出（对应 Python 版托盘）。
fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let mi_popup = MenuItem::with_id(app, "popup", "弹窗", true, None::<&str>)?;
    let mi_settings = MenuItem::with_id(app, "settings", "设置…", true, None::<&str>)?;
    let mi_config = MenuItem::with_id(app, "config_file", "打开配置文件", true, None::<&str>)?;
    let mi_quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&mi_popup, &mi_settings, &mi_config, &mi_quit])?;

    let mut tray = TrayIconBuilder::with_id("main-tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("懂译·Rust")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "popup" => {
                let _ = show_popup(app.clone());
            }
            "settings" => {
                let _ = show_settings(app.clone());
            }
            "config_file" => {
                // 配置文件（模型/base_url/api_key 都在这里改；改完托盘点重启）
                let path = dongyi_core::config_path();
                if let Err(e) = app.opener().open_path(path.to_string_lossy(), None::<&str>) {
                    eprintln!("[tray] 打开配置文件失败: {e}");
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Windows 实测：左键成对发 Click{Down} + Click{Up}；只在 Up 切换，避免双计
            // 置顶提示：隐藏也走 Close 等规编排入口（Gate P3-B2）
            if let tauri::tray::TrayIconEvent::Click {
                button: tauri::tray::MouseButton::Left,
                button_state: tauri::tray::MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                let visible = app
                    .get_webview_window(POPUP_LABEL)
                    .and_then(|w| w.is_visible().ok())
                    .unwrap_or(false);
                if visible {
                    // 隐藏走编排（断流 + 复位），与 Esc/点外同规
                    send_orchestrator(app, orchestrator::AppEvent::Close);
                } else {
                    // 显示不新建会话：展示现有内容
                    let _ = show_popup(app.clone());
                }
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}
