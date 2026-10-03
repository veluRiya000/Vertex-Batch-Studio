#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use base64::{engine::general_purpose::STANDARD, Engine};
use futures_util::StreamExt;
use reqwest::{Client, Method, Response};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, OnceLock,
    },
    time::Duration,
};
use tauri::{
    ipc::Channel,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, State, WindowEvent,
};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

type Result<T> = std::result::Result<T, String>;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Preferences {
    theme: String,
    language: String,
    close_to_tray: bool,
    auto_start: bool,
    start_minimized: bool,
    sidebar_width: u16,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            theme: "light".into(),
            language: "zh-CN".into(),
            close_to_tray: true,
            auto_start: false,
            start_minimized: false,
            sidebar_width: 258,
        }
    }
}
impl Preferences {
    fn validate(&self) -> Result<()> {
        if !matches!(self.theme.as_str(), "light" | "dark")
            || !matches!(self.language.as_str(), "zh-CN" | "en")
            || self.sidebar_width > 420
        {
            return Err("设置参数无效".into());
        }
        Ok(())
    }
}

#[derive(Clone, Deserialize)]
struct Connection {
    url: String,
    token: String,
}

struct Studio {
    root: PathBuf,
    client: Client,
    connection: Mutex<Option<Connection>>,
    preferences: Mutex<Preferences>,
    child: Mutex<Option<Child>>,
    watchers: Mutex<HashMap<String, tokio::sync::watch::Sender<bool>>>,
    quitting: AtomicBool,
    stopped: AtomicBool,
    smoke: bool,
}

fn valid_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

// Match the same operations as the former desktop bridge, without arbitrary URLs.
fn allowed(method: &str, path: &str) -> bool {
    if path.len() > 4096
        || !path.starts_with('/')
        || path.starts_with("//")
        || path.contains(['\\', '\r', '\n', '#'])
    {
        return false;
    }
    let pathname = path.split('?').next().unwrap_or("");
    static RULES: OnceLock<HashMap<&'static str, Vec<regex::Regex>>> = OnceLock::new();
    let rules = RULES.get_or_init(|| {
        let id = "[a-f0-9]{32}";
        [
            ("GET", vec!["^/(health|config|preferences|references|batches)$".into(),
                "^/references/file$".into(),
                format!("^/batches/{id}(/tasks|/results|/images/{id}/[0-9]+)?$")]),
            ("POST", vec!["^/(batches|references/import|cloud/check)$".into(),
                format!("^/batches/{id}/(tasks|prepare|submit|poll|extract|cancel|retry|clone|archive|attach|import-jsonl)$")]),
            ("PUT", vec!["^/(preferences|cloud/configuration|references/order)$".into(),
                format!("^/batches/{id}/(tasks|output-directory|tasks/{id})$")]),
            ("DELETE", vec![format!("^/batches/{id}/tasks/{id}$")]),
        ].into_iter().map(|(method, patterns)|
            (method, patterns.into_iter().map(|p: String| regex::Regex::new(&p).unwrap()).collect())
        ).collect()
    });
    rules
        .get(method)
        .is_some_and(|rules| rules.iter().any(|r| r.is_match(pathname)))
}

impl Studio {
    fn read_connection(&self) -> Result<Connection> {
        let bytes =
            fs::read(self.root.join(".runtime/connection.json")).map_err(|e| e.to_string())?;
        let value: Connection = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        let url = reqwest::Url::parse(&value.url).map_err(|e| e.to_string())?;
        if url.scheme() != "http"
            || url.host_str() != Some("127.0.0.1")
            || url.port().is_none()
            || url.path() != "/"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || value.token.is_empty()
        {
            return Err("本地连接记录无效".into());
        }
        Ok(value)
    }

    async fn healthy(&self, connection: &Connection) -> bool {
        let result = self
            .client
            .get(format!("{}/health", connection.url))
            .header("X-VBS-Token", &connection.token)
            .timeout(Duration::from_secs(2))
            .send()
            .await;
        match result {
            Ok(response) if response.status().is_success() => response
                .json::<Value>()
                .await
                .is_ok_and(|v| v["status"] == "ok"),
            _ => false,
        }
    }

    async fn start(&self, app: &AppHandle) -> Result<()> {
        if let Ok(value) = self.read_connection() {
            if self.healthy(&value).await {
                *self.connection.lock().unwrap() = Some(value);
                return Ok(());
            }
        }
        let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
        let frozen = resources.join("backend/vertex-backend.exe");
        let mut command;
        // VBS_PYTHON is only a development override, never used by release builds.
        if cfg!(debug_assertions) {
            let python = std::env::var_os("VBS_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|| self.root.join(".venv/Scripts/python.exe"));
            command = Command::new(python);
            command.args(["-X", "utf8", "-m", "backend", "--root"]);
            command.arg(&self.root);
        } else {
            if !frozen.is_file() {
                return Err("找不到后端运行文件，请重新安装".into());
            }
            command = Command::new(frozen);
            command.arg("--root").arg(&self.root);
        }
        command
            .args(["serve", "--port", "0"])
            .current_dir(&self.root)
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::null());
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join(".runtime/desktop-backend.log"))
            .map_err(|e| e.to_string())?;
        command
            .stdout(log.try_clone().map_err(|e| e.to_string())?)
            .stderr(log);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        *self.child.lock().unwrap() = Some(command.spawn().map_err(|e| e.to_string())?);
        for _ in 0..150 {
            {
                let mut child = self.child.lock().unwrap();
                if let Some(child) = child.as_mut() {
                    if let Some(code) = child.try_wait().map_err(|e| e.to_string())? {
                        return Err(format!(
                            "后端启动失败 ({code})，请检查 .runtime/desktop-backend.log"
                        ));
                    }
                }
            }
            if let Ok(value) = self.read_connection() {
                if self.healthy(&value).await {
                    *self.connection.lock().unwrap() = Some(value);
                    return Ok(());
                }
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        Err("本地后端启动超时，请检查 .runtime/desktop-backend.log".into())
    }

    fn request(&self, method: Method, path: &str) -> Result<reqwest::RequestBuilder> {
        let connection = self
            .connection
            .lock()
            .unwrap()
            .clone()
            .ok_or("后端尚未连接")?;
        Ok(self
            .client
            .request(method, format!("{}{path}", connection.url))
            .header("X-VBS-Token", connection.token))
    }

    async fn json(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        let mut request = self
            .request(method, path)?
            .timeout(Duration::from_secs(120));
        if let Some(body) = body {
            request = request.json(&body);
        }
        decode_json(request.send().await.map_err(|e| e.to_string())?).await
    }

    async fn stop(&self) {
        for (_, cancel) in self.watchers.lock().unwrap().drain() {
            let _ = cancel.send(true);
        }
        // Leave a separately launched development server running.
        if self.child.lock().unwrap().is_none() {
            return;
        }
        if let Ok(request) = self.request(Method::POST, "/shutdown") {
            let _ = request.timeout(Duration::from_secs(10)).send().await;
        }
        for _ in 0..100 {
            let exited = self
                .child
                .lock()
                .unwrap()
                .as_mut()
                .is_none_or(|child| child.try_wait().ok().flatten().is_some());
            if exited {
                return;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        if let Some(child) = self.child.lock().unwrap().as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

async fn decode_json(response: Response) -> Result<Value> {
    let status = response.status();
    if status.as_u16() == 204 {
        return Ok(Value::Null);
    }
    let value = response.json::<Value>().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(value["detail"]
            .as_str()
            .unwrap_or("请求参数有误，请检查输入内容")
            .into());
    }
    Ok(value)
}

#[tauri::command]
async fn studio_api(
    studio: State<'_, Arc<Studio>>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value> {
    if !allowed(&method, &path) {
        return Err("不支持的工作室操作".into());
    }
    studio
        .json(
            Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?,
            &path,
            body,
        )
        .await
}

#[tauri::command]
async fn studio_image(studio: State<'_, Arc<Studio>>, path: String) -> Result<String> {
    if !allowed("GET", &path)
        || !(path.starts_with("/references/file?") || path.contains("/images/"))
    {
        return Err("图片路径无效".into());
    }
    let response = studio
        .request(Method::GET, &path)?
        .timeout(Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !response.status().is_success() {
        return Err("图片暂不可用".into());
    }
    let mime = response
        .headers()
        .get("content-type")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("")
        .to_string();
    if !matches!(mime.as_str(), "image/png" | "image/jpeg" | "image/webp") {
        return Err("图片格式无效".into());
    }
    let bytes = response.bytes().await.map_err(|e| e.to_string())?;
    Ok(format!("data:{mime};base64,{}", STANDARD.encode(bytes)))
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ImportOptions {
    category: Option<String>,
    batch_id: Option<String>,
}

#[tauri::command]
async fn studio_upload(
    studio: State<'_, Arc<Studio>>,
    name: String,
    bytes: Vec<u8>,
    options: ImportOptions,
) -> Result<Value> {
    if bytes.len() > 30 * 1024 * 1024 || name.len() > 1024 {
        return Err("图片过大或名称无效".into());
    }
    if options.batch_id.as_ref().is_some_and(|id| !valid_id(id)) {
        return Err("导入目标无效".into());
    }
    let mut query = vec![("name", name)];
    if let Some(category) = options.category {
        query.push(("category", category));
    }
    if let Some(id) = options.batch_id {
        query.push(("batch_id", id));
    }
    let response = studio
        .request(Method::POST, "/references/upload")?
        .query(&query)
        .body(bytes)
        .timeout(Duration::from_secs(120))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    decode_json(response).await
}

#[tauri::command]
async fn choose_directory(app: AppHandle) -> Result<Option<String>> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("选择图片保存文件夹")
            .blocking_pick_folder()
            .map(|p| {
                p.into_path()
                    .map(|p| p.to_string_lossy().into_owned())
                    .map_err(|e| e.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn open_output(app: AppHandle, studio: State<'_, Arc<Studio>>, id: String) -> Result<()> {
    if !valid_id(&id) {
        return Err("批次编号无效".into());
    }
    let batch = studio
        .json(Method::GET, &format!("/batches/{id}"), None)
        .await?;
    let config = studio.json(Method::GET, "/config", None).await?;
    let output = if let Some(path) = batch["image_output_dir"].as_str() {
        PathBuf::from(path)
    } else {
        PathBuf::from(config["data_dir"].as_str().ok_or("数据目录无效")?)
            .join(if batch["archived"] == true {
                "archive"
            } else {
                "batches"
            })
            .join(batch["folder"].as_str().ok_or("批次目录无效")?)
            .join("outputs/images")
    };
    if !output.is_absolute() {
        return Err("输出目录无效".into());
    }
    fs::create_dir_all(&output).map_err(|e| e.to_string())?;
    app.opener()
        .open_path(output.to_string_lossy().into_owned(), None::<&str>)
        .map_err(|e| e.to_string())
}

fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn tray_menu(app: &AppHandle, english: bool) -> tauri::Result<Menu<tauri::Wry>> {
    let open = MenuItem::with_id(
        app,
        "open",
        if english {
            "Open studio"
        } else {
            "打开工作室"
        },
        true,
        None::<&str>,
    )?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(
        app,
        "quit",
        if english {
            "Quit studio"
        } else {
            "退出工作室"
        },
        true,
        None::<&str>,
    )?;
    Menu::with_items(app, &[&open, &separator, &quit])
}

#[tauri::command]
async fn set_preferences(
    app: AppHandle,
    studio: State<'_, Arc<Studio>>,
    value: Preferences,
) -> Result<Value> {
    value.validate()?;
    let before = studio.preferences.lock().unwrap().clone();
    let changed = value.auto_start != before.auto_start;
    if changed {
        let result = if value.auto_start {
            app.autolaunch().enable()
        } else {
            app.autolaunch().disable()
        };
        result.map_err(|e| e.to_string())?;
    }
    let result = studio
        .json(
            Method::PUT,
            "/preferences",
            Some(serde_json::to_value(&value).unwrap()),
        )
        .await;
    match result {
        Ok(saved) => {
            *studio.preferences.lock().unwrap() = value.clone();
            if let Some(tray) = app.tray_by_id("studio") {
                let _ = tray.set_menu(Some(
                    tray_menu(&app, value.language == "en").map_err(|e| e.to_string())?,
                ));
            }
            Ok(saved)
        }
        Err(error) => {
            if changed {
                let _ = if before.auto_start {
                    app.autolaunch().enable()
                } else {
                    app.autolaunch().disable()
                };
            }
            Err(error)
        }
    }
}

#[tauri::command]
fn window_action(app: AppHandle, action: String) -> Result<()> {
    let window = app.get_webview_window("main").ok_or("窗口不可用")?;
    let result = match action.as_str() {
        "minimize" => window.minimize(),
        "maximize" => {
            if window.is_maximized().map_err(|e| e.to_string())? {
                window.unmaximize()
            } else {
                window.maximize()
            }
        }
        "hide" => window.close(),
        "quit" => {
            app.exit(0);
            return Ok(());
        }
        _ => return Err("窗口操作无效".into()),
    };
    result.map_err(|e| e.to_string())
}

#[tauri::command]
fn watch_batch(
    studio: State<'_, Arc<Studio>>,
    key: String,
    id: String,
    channel: Channel<Value>,
) -> Result<()> {
    if !valid_id(&id) || key.is_empty() || key.len() > 100 {
        return Err("进度订阅无效".into());
    }
    let (cancel, receiver) = tokio::sync::watch::channel(false);
    {
        let mut watchers = studio.watchers.lock().unwrap();
        if watchers.len() >= 64 {
            return Err("进度订阅过多".into());
        }
        if watchers.contains_key(&key) {
            return Err("进度订阅编号已存在".into());
        }
        watchers.insert(key.clone(), cancel.clone());
    }
    let studio = studio.inner().clone();
    tauri::async_runtime::spawn(async move {
        stream_events(studio.clone(), id, channel, receiver).await;
        let mut watchers = studio.watchers.lock().unwrap();
        if watchers
            .get(&key)
            .is_some_and(|current| current.same_channel(&cancel))
        {
            watchers.remove(&key);
        }
    });
    Ok(())
}

#[tauri::command]
fn unwatch_batch(studio: State<'_, Arc<Studio>>, key: String) {
    if let Some(cancel) = studio.watchers.lock().unwrap().remove(&key) {
        let _ = cancel.send(true);
    }
}

async fn stream_events(
    studio: Arc<Studio>,
    id: String,
    channel: Channel<Value>,
    mut cancel: tokio::sync::watch::Receiver<bool>,
) {
    // Dropping the in-flight request or stream cancels it immediately on unmount/exit.
    while !*cancel.borrow() {
        let request = match studio.request(Method::GET, &format!("/batches/{id}/events")) {
            Ok(r) => r,
            Err(_) => return,
        };
        let response = tokio::select! {
            _ = cancel.changed() => return,
            response = request.send() => response,
        };
        if let Ok(response) = response {
            if response.status().is_success() {
                let mut stream = response.bytes_stream();
                let mut buffer = Vec::<u8>::new();
                loop {
                    let chunk = tokio::select! {
                        _ = cancel.changed() => return,
                        chunk = stream.next() => chunk,
                    };
                    let Some(Ok(chunk)) = chunk else {
                        break;
                    };
                    buffer.extend(chunk.iter().copied().filter(|b| *b != b'\r'));
                    if buffer.len() > 8 * 1024 * 1024 {
                        break;
                    }
                    while let Some(end) = buffer.windows(2).position(|w| w == b"\n\n") {
                        let event = buffer.drain(..end + 2).collect::<Vec<_>>();
                        let text = String::from_utf8_lossy(&event);
                        let data = text
                            .lines()
                            .filter_map(|l| l.strip_prefix("data:"))
                            .map(str::trim)
                            .collect::<Vec<_>>()
                            .join("\n");
                        if let Ok(snapshot) = serde_json::from_str::<Value>(&data) {
                            let terminal = matches!(
                                snapshot["batch"]["phase"].as_str(),
                                Some(
                                    "completed" | "completed_with_errors" | "failed" | "cancelled"
                                )
                            );
                            if channel.send(snapshot).is_err() || terminal {
                                return;
                            }
                        }
                    }
                }
            }
        }
        tokio::select! {
            _ = cancel.changed() => return,
            _ = tokio::time::sleep(Duration::from_secs(3)) => {},
        }
    }
}

fn main() {
    let smoke = std::env::args().any(|a| a == "--smoke-test");
    let test_mode = smoke || std::env::args().any(|a| a == "--ui-test");
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_window(app)
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .app_name(if test_mode {
                    "VertexBatchStudio-install-test"
                } else {
                    "VertexBatchStudio"
                })
                .args(["--startup"])
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            studio_api,
            studio_image,
            studio_upload,
            choose_directory,
            open_output,
            set_preferences,
            window_action,
            watch_batch,
            unwatch_batch,
            renderer_ready,
            smoke_mode,
            renderer_failed
        ])
        .setup(move |app| {
            let root = if test_mode || !cfg!(debug_assertions) {
                PathBuf::from(std::env::var_os("APPDATA").ok_or("APPDATA is unavailable")?).join(
                    if smoke {
                        "VertexBatchStudio-smoke-test"
                    } else if test_mode {
                        "VertexBatchStudio-install-test"
                    } else {
                        "VertexBatchStudio"
                    },
                )
            } else {
                std::env::var_os("VBS_ROOT")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
                    .canonicalize()?
            };
            fs::create_dir_all(root.join(".runtime"))?;
            let preferences = fs::read(root.join("settings.json"))
                .ok()
                .and_then(|b| serde_json::from_slice::<Preferences>(&b).ok())
                .filter(|p| p.validate().is_ok())
                .unwrap_or_default();
            let studio = Arc::new(Studio {
                root,
                preferences: Mutex::new(preferences.clone()),
                connection: Mutex::new(None),
                child: Mutex::new(None),
                watchers: Mutex::new(HashMap::new()),
                quitting: AtomicBool::new(false),
                stopped: AtomicBool::new(false),
                smoke,
                client: Client::builder()
                    .no_proxy()
                    .redirect(reqwest::redirect::Policy::none())
                    .connect_timeout(Duration::from_secs(3))
                    .build()?,
            });
            app.manage(studio.clone());
            if let Err(error) = tauri::async_runtime::block_on(studio.start(app.handle())) {
                tauri::async_runtime::block_on(studio.stop());
                app.dialog()
                    .message(&error)
                    .title("工作室启动未完成")
                    .blocking_show();
                return Err(error.into());
            }
            // Keep an already enabled startup entry pointing at the new executable after upgrades.
            if !smoke && !cfg!(debug_assertions) && preferences.auto_start {
                app.autolaunch().enable()?;
            }
            TrayIconBuilder::with_id("studio")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Vertex Batch Studio")
                .menu(&tray_menu(app.handle(), preferences.language == "en")?)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        show_window(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let studio = window.state::<Arc<Studio>>();
                if !studio.quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    if studio.preferences.lock().unwrap().close_to_tray {
                        let _ = window.hide();
                    } else {
                        window.app_handle().exit(0);
                    }
                }
            }
        });
    let app = builder
        .build(tauri::generate_context!())
        .expect("Desktop initialization failed");
    app.run(|app, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            let Some(studio) = app.try_state::<Arc<Studio>>() else {
                return;
            };
            if !studio.stopped.load(Ordering::SeqCst) {
                api.prevent_exit();
                if studio.quitting.swap(true, Ordering::SeqCst) {
                    return;
                }
                let studio = studio.inner().clone();
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    studio.stop().await;
                    studio.stopped.store(true, Ordering::SeqCst);
                    app.exit(0);
                });
            }
        }
    });
}

#[tauri::command]
async fn renderer_ready(app: AppHandle, studio: State<'_, Arc<Studio>>) -> Result<()> {
    // Called only after React rendered and /health succeeded, not just page navigation.
    if studio.smoke {
        let health = studio.json(Method::GET, "/health", None).await?;
        if health["status"] != "ok" {
            return Err("后端健康检查失败".into());
        }
        fs::write(studio.root.join(".runtime/tauri-smoke.json"),
            serde_json::to_vec(&json!({"packaged": !cfg!(debug_assertions), "rendererLoaded": true, "backendHealthy": true,
                "imageImportPreview": true, "taskReferencesAndCount": true, "preferences": true, "sse": true, "windowControls": true,
                "unconfiguredSubmissionRejected": true, "localCancellation": true, "cloudIndicator": true})).unwrap())
            .map_err(|e| e.to_string())?;
        app.exit(0);
    } else if !studio.preferences.lock().unwrap().start_minimized {
        show_window(&app);
    }
    Ok(())
}

#[tauri::command]
fn smoke_mode(studio: State<'_, Arc<Studio>>) -> bool {
    studio.smoke
}

#[tauri::command]
fn renderer_failed(app: AppHandle, studio: State<'_, Arc<Studio>>, message: String) {
    let _ = fs::write(
        studio.root.join(".runtime/desktop-renderer-error.log"),
        &message,
    );
    if studio.smoke {
        app.exit(1);
    } else {
        show_window(&app);
        app.dialog()
            .message("界面连接未完成，请查看 .runtime/desktop-renderer-error.log")
            .title("工作室启动未完成")
            .show(|_| {});
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn desktop_bridge_rejects_external_and_encoded_routes() {
        let id = "a".repeat(32);
        assert!(allowed("GET", &format!("/batches/{id}/results")));
        assert!(allowed("GET", "/references/file?path=styles%2Fa.png"));
        for path in [
            "//evil.test/config",
            "https://evil.test",
            "/config#x",
            "/../config",
            "/%63onfig",
            "/config\\x",
            "/shutdown",
        ] {
            assert!(!allowed("GET", path), "{path}");
        }
        assert!(!allowed("POST", "/preferences"));
        assert!(!valid_id(&"A".repeat(32)));
    }
    #[test]
    fn preferences_reject_out_of_range_and_unknown_fields() {
        let mut value = Preferences::default();
        value.sidebar_width = 421;
        assert!(value.validate().is_err());
        assert!(
            serde_json::from_value::<Preferences>(json!({"theme":"light","unknown":true})).is_err()
        );
    }
}
