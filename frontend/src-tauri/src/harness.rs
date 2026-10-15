//! The DSH webview has no access to the image studio's native commands.
use super::{Result, Studio};
use serde_json::json;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};
use tauri::{AppHandle, Manager, State, LogicalPosition, LogicalSize, WebviewUrl, webview::WebviewBuilder};

#[derive(Default)]
pub struct HarnessView {
    gate: tokio::sync::Mutex<()>,
    visible: AtomicBool,
}

pub fn resize(app: &AppHandle) {
    if let (Some(main), Some(view)) = (app.get_window("main"), app.get_webview("harness")) {
        if let (Ok(size),Ok(scale)) = (main.inner_size(), main.scale_factor()) {
            let size: tauri::LogicalSize<f64> = size.to_logical(scale);
            let _ = view.set_position(LogicalPosition::new(0.,54.));
            let _ = view.set_size(LogicalSize::new(size.width,(size.height-54.).max(1.)));
        }
    }
}

#[tauri::command]
pub async fn harness_view(app:AppHandle, studio:State<'_,Arc<Studio>>, state:State<'_,HarnessView>, visible:bool, offline:bool, restore_only:Option<bool>) -> Result<()> {
    state.visible.store(visible, Ordering::SeqCst);
    // Visibility changes never wait for startup or its network request. The
    // existing webview retains the conversation, scroll position and draft.
    if !visible {
        if let Some(view)=app.get_webview("harness") {view.hide().map_err(|e|e.to_string())?;}
        return Ok(());
    }
    if restore_only.unwrap_or(false) {
        if let Some(view)=app.get_webview("harness") {
            // Window resize/scale events already size even hidden views. Do
            // not synchronously query window geometry on every warm switch.
            view.show().map_err(|e|e.to_string())?;
            view.set_focus().map_err(|e|e.to_string())?;
            return Ok(());
        }
    }
    // Only first creation or an explicit start verifies the backend and origin.
    let _gate=state.gate.lock().await;
    // Startup may finish while hidden; final visibility follows the latest
    // mode/modal request instead of aborting first startup when React hides it.
    let result=studio.json(reqwest::Method::POST,"/harness/start",Some(json!({"offline":offline}))).await?;
    let url=reqwest::Url::parse(result["url"].as_str().ok_or("Harness 地址无效")?).map_err(|e|e.to_string())?;
        if url.scheme()!="http" || url.host_str()!=Some("127.0.0.1") || url.port().is_none() || url.path()!="/" {
            return Err("拒绝非本机 Harness 地址".into());
        }
    if let Some(view)=app.get_webview("harness") {
        if view.url().map_err(|e|e.to_string())?.origin()!=url.origin() {view.close().map_err(|e|e.to_string())?;}
    }
    if app.get_webview("harness").is_none() {
        let origin=url.origin();
        let main=app.get_window("main").ok_or("窗口不可用")?;
        let size:tauri::LogicalSize<f64>=main.inner_size().map_err(|e|e.to_string())?.to_logical(main.scale_factor().map_err(|e|e.to_string())?);
        let mut view=WebviewBuilder::new("harness",WebviewUrl::External(url))
            // DSH owns HTML5 file drops and validates/uploads through its composer.
            // WebView2's native handler otherwise swallows these events on Windows.
            .disable_drag_drop_handler()
            .on_navigation(move |target| target.origin()==origin);
        // The acceptance-only debug configuration supplies this for both views.
        #[cfg(debug_assertions)]
        if let Some(args)=app.config().app.windows.iter().find(|w|w.label=="main").and_then(|w|w.additional_browser_args.as_deref()) {
            view=view.additional_browser_args(args);
        }
        main.add_child(view,LogicalPosition::new(0.,54.),LogicalSize::new(size.width,(size.height-54.).max(1.))).map_err(|e|e.to_string())?;
    }
    resize(&app);
    if let Some(view)=app.get_webview("harness") {
        if state.visible.load(Ordering::SeqCst) {view.show().map_err(|e|e.to_string())?;view.set_focus().map_err(|e|e.to_string())?;}
        else {view.hide().map_err(|e|e.to_string())?;}
    }
    Ok(())
}
