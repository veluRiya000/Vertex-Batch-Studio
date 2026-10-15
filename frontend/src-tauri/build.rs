fn main() {
    println!("cargo:rerun-if-changed=icons/icon.ico");
    println!("cargo:rerun-if-changed=icons/icon.png");
    // Application commands are governed by the same webview ACL as plugin commands.
    // The remote Harness child receives none of these permissions.
    tauri_build::try_build(tauri_build::Attributes::new()
        .windows_attributes(tauri_build::WindowsAttributes::new().window_icon_path("icons/icon.ico"))
        .app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "studio_api", "studio_image", "studio_upload", "choose_directory",
            "open_output", "set_preferences", "window_action", "watch_batch",
            "unwatch_batch", "renderer_ready", "smoke_mode", "renderer_failed", "harness_view", "open_cloud_page",
        ])
    )).expect("desktop build configuration failed");
}
