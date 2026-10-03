// The renderer receives narrow actions only. Credentials and the local token stay here.
const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  Tray,
  Menu,
  nativeImage,
  shell,
} = require("electron");
const {
  readFileSync,
  mkdirSync,
  existsSync,
  createWriteStream,
} = require("node:fs");
const { resolve, join, isAbsolute } = require("node:path");
const { pathToFileURL } = require("node:url");
const { spawn } = require("node:child_process");
const root = resolve(__dirname, "../..");
const runtime = join(root, ".runtime");
mkdirSync(runtime, { recursive: true });
app.setPath("userData", join(runtime, "desktop"));
app.setPath("sessionData", join(runtime, "desktop-cache"));
app.setName("Vertex Batch Studio");
let window,
  tray,
  backend,
  connection,
  quitting = false,
  stopped = false;
const subscriptions = new Map();
const defaults = {
  theme: "light",
  language: "zh-CN",
  close_to_tray: true,
  auto_start: false,
  start_minimized: false,
  sidebar_width: 258,
};
let preferences = { ...defaults };
function validatePreferences(value) {
  if (
    !value ||
    typeof value !== "object" ||
    Object.keys(value).some((key) => !(key in defaults)) ||
    !["light", "dark"].includes(value.theme) ||
    !["zh-CN", "en"].includes(value.language) ||
    !["close_to_tray", "auto_start", "start_minimized"].every(
      (key) => typeof value[key] === "boolean",
    ) ||
    !Number.isInteger(value.sidebar_width) ||
    value.sidebar_width < 0 ||
    value.sidebar_width > 420
  )
    throw new Error("设置参数无效");
  return value;
}
function loadPreferences() {
  try {
    preferences = validatePreferences(
      JSON.parse(readFileSync(join(root, "settings.json"), "utf8")),
    );
  } catch {
    preferences = { ...defaults };
  }
}
function loginOptions(enabled) {
  return {
    name: "VertexBatchStudio",
    openAtLogin: enabled,
    path: process.execPath,
    args: [app.getAppPath(), "--startup"],
  };
}
function updateTray() {
  if (!tray) return;
  const english = preferences.language === "en";
  tray.setToolTip("Vertex Batch Studio");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: english ? "Open studio" : "打开工作室",
        click: () => {
          window.show();
          window.focus();
        },
      },
      { type: "separator" },
      {
        label: english ? "Quit studio" : "退出工作室",
        click: () => app.quit(),
      },
    ]),
  );
}
const page = pathToFileURL(resolve(__dirname, "../dist/index.html")).href;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function readConnection() {
  const value = JSON.parse(
    readFileSync(join(runtime, "connection.json"), "utf8"),
  );
  if (
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(value.url) ||
    typeof value.token !== "string" ||
    !value.token
  )
    throw new Error("本地连接记录无效");
  return value;
}
async function request(path, options = {}) {
  connection = readConnection();
  return fetch(connection.url + path, {
    ...options,
    headers: { "X-VBS-Token": connection.token, ...options.headers },
  });
}
async function healthy(value) {
  try {
    const response = await fetch(value.url + "/health", {
      headers: { "X-VBS-Token": value.token },
      signal: AbortSignal.timeout(1500),
    });
    return response.ok && (await response.json()).status === "ok";
  } catch {
    return false;
  }
}
async function startBackend() {
  try {
    const value = readConnection();
    if (await healthy(value)) {
      connection = value;
      return;
    }
  } catch {}
  const python = join(root, ".venv/Scripts/python.exe");
  if (!existsSync(python))
    throw new Error("找不到 Python 环境，请先完成后端环境安装");
  const log = createWriteStream(join(runtime, "desktop-backend.log"), {
    flags: "a",
  });
  backend = spawn(
    python,
    ["-X", "utf8", "-m", "backend", "serve", "--port", "0"],
    {
      cwd: root,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    },
  );
  backend.stdout.pipe(log, { end: false });
  backend.stderr.pipe(log, { end: false });
  let failure;
  backend.once("error", (error) => {
    failure = error;
  });
  backend.once("exit", (code) => {
    failure = new Error(
      "后端启动未完成，请检查 .runtime/desktop-backend.log（退出码 " +
        code +
        "）",
    );
    log.end();
  });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (failure) throw failure;
    try {
      const value = readConnection();
      if (await healthy(value)) {
        connection = value;
        return;
      }
    } catch {}
    await pause(200);
  }
  throw new Error("本地后端启动超时，请检查 .runtime/desktop-backend.log");
}
function trusted(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    event.senderFrame.url !== page
  )
    throw new Error("只接受工作室窗口的请求");
}
function allowed(method, path) {
  if (
    typeof path !== "string" ||
    path.length > 4096 ||
    !path.startsWith("/") ||
    path.includes("\\") ||
    /[\r\n#]/.test(path)
  )
    return false;
  const url = new URL(path, "http://127.0.0.1");
  if (url.origin !== "http://127.0.0.1" || url.pathname.includes(".."))
    return false;
  const id = "[a-f0-9]{32}";
  const rules = {
    GET: [
      /^\/(health|config|preferences|references|batches)$/,
      /^\/references\/file$/,
      new RegExp(`^/batches/${id}(/tasks|/results|/images/${id}/[0-9]+)?$`),
    ],
    POST: [
      /^\/(batches|references\/import|cloud\/check)$/,
      new RegExp(
        `^/batches/${id}/(tasks|prepare|submit|poll|extract|cancel|retry|clone|archive|attach|import-jsonl)$`,
      ),
    ],
    PUT: [
      /^\/(preferences|cloud\/configuration|references\/order)$/,
      new RegExp(`^/batches/${id}/(tasks|output-directory|tasks/${id})$`),
    ],
    DELETE: [new RegExp(`^/batches/${id}/tasks/${id}$`)],
  };
  return (rules[method] || []).some((rule) => rule.test(url.pathname));
}
async function json(response) {
  if (response.status === 204) return undefined;
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : "请求参数有误",
    );
  return data;
}
async function watch(key, batchId, sender) {
  const controller = new AbortController();
  subscriptions.set(key, controller);
  try {
    while (!controller.signal.aborted && !sender.isDestroyed()) {
      try {
        const response = await request(`/batches/${batchId}/events`, {
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error("进度连接中断");
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder
            .decode(chunk.value, { stream: true })
            .replace(/\r/g, "");
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const data = event
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("\n");
            if (data && !sender.isDestroyed()) {
              const snapshot = JSON.parse(data);
              sender.send("studio:snapshot", key, snapshot);
              if (
                [
                  "completed",
                  "completed_with_errors",
                  "failed",
                  "cancelled",
                ].includes(snapshot.batch.phase)
              ) {
                controller.abort();
                return;
              }
            }
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      await pause(3000);
    }
  } finally {
    if (subscriptions.get(key) === controller) subscriptions.delete(key);
  }
}
function setupBridge() {
  ipcMain.handle("studio:preferences", async (event, value) => {
    trusted(event);
    validatePreferences(value);
    const before = preferences;
    // Only touch Windows startup when the user changes this switch.
    if (value.auto_start !== before.auto_start)
      app.setLoginItemSettings(loginOptions(value.auto_start));
    try {
      preferences = await json(
        await request("/preferences", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(value),
        }),
      );
    } catch (error) {
      if (value.auto_start !== before.auto_start)
        app.setLoginItemSettings(loginOptions(before.auto_start));
      throw error;
    }
    updateTray();
    return preferences;
  });
  ipcMain.handle("studio:api", async (event, method, path, body) => {
    trusted(event);
    if (!allowed(method, path)) throw new Error("不支持的工作室操作");
    return json(
      await request(path, {
        method,
        headers:
          body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
  });
  ipcMain.handle("studio:image", async (event, path) => {
    trusted(event);
    if (
      !allowed("GET", path) ||
      !/^\/(references\/file\?|batches\/[a-f0-9]{32}\/images\/)/.test(path)
    )
      throw new Error("图片路径无效");
    const response = await request(path);
    if (!response.ok) throw new Error("图片暂不可用");
    const mime = response.headers.get("content-type")?.split(";")[0];
    if (!["image/png", "image/jpeg", "image/webp"].includes(mime))
      throw new Error("图片格式无效");
    return `data:${mime};base64,${Buffer.from(await response.arrayBuffer()).toString("base64")}`;
  });
  ipcMain.handle("studio:upload", async (event, name, bytes, options) => {
    trusted(event);
    if (
      typeof name !== "string" ||
      !(bytes instanceof ArrayBuffer) ||
      bytes.byteLength > 30 * 1024 * 1024
    )
      throw new Error("图片过大或格式无效");
    if (
      !options ||
      Object.keys(options).some(
        (key) => !["category", "batch_id"].includes(key),
      )
    )
      throw new Error("导入目标无效");
    const query = new URLSearchParams({ name, ...options });
    return json(
      await request("/references/upload?" + query, {
        method: "POST",
        body: Buffer.from(bytes),
      }),
    );
  });
  ipcMain.handle("studio:directory", async (event) => {
    trusted(event);
    const result = await dialog.showOpenDialog(window, {
      title: "选择图片保存文件夹",
      properties: ["openDirectory", "createDirectory"],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("studio:output", async (event, id) => {
    trusted(event);
    if (!/^[a-f0-9]{32}$/.test(id)) throw new Error("批次编号无效");
    const batch = await json(await request("/batches/" + id)),
      config = await json(await request("/config"));
    const output =
      batch.image_output_dir ||
      join(
        config.data_dir,
        batch.archived ? "archive" : "batches",
        batch.folder,
        "outputs/images",
      );
    if (!isAbsolute(output)) throw new Error("输出目录无效");
    mkdirSync(output, { recursive: true });
    const error = await shell.openPath(output);
    if (error) throw new Error(error);
  });
  ipcMain.on("studio:watch", (event, key, id) => {
    trusted(event);
    if (
      !/^[a-f0-9]{32}$/.test(id) ||
      typeof key !== "string" ||
      key.length > 100 ||
      subscriptions.size >= 64
    )
      return;
    subscriptions.get(key)?.abort();
    void watch(key, id, event.sender);
  });
  ipcMain.on("studio:unwatch", (event, key) => {
    trusted(event);
    subscriptions.get(key)?.abort();
  });
  ipcMain.on("studio:window", (event, action) => {
    trusted(event);
    if (action === "minimize") window.minimize();
    if (action === "maximize")
      window.isMaximized() ? window.unmaximize() : window.maximize();
    if (action === "hide") window.close();
    if (action === "quit") app.quit();
  });
}
async function stopBackend() {
  for (const controller of subscriptions.values()) controller.abort();
  try {
    await request("/shutdown", {
      method: "POST",
      signal: AbortSignal.timeout(10000),
    });
  } catch {}
  if (backend && backend.exitCode === null) {
    for (let i = 0; i < 100 && backend.exitCode === null; i++) await pause(100);
  }
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      window.show();
      window.focus();
    }
  });
  app.whenReady().then(async () => {
    try {
      await startBackend();
      loadPreferences();
      setupBridge();
      const icon = nativeImage.createFromPath(join(__dirname, "icon.png"));
      window = new BrowserWindow({
        width: 1440,
        height: 940,
        minWidth: 900,
        minHeight: 650,
        frame: false,
        show: false,
        title: "Vertex Batch Studio",
        backgroundColor: preferences.theme === "dark" ? "#141f2c" : "#FBFCFE",
        icon,
        webPreferences: {
          preload: join(__dirname, "preload.cjs"),
          nodeIntegration: false,
          contextIsolation: true,
          sandbox: true,
          webviewTag: false,
        },
      });
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event, url) => {
        if (url !== page) event.preventDefault();
      });
      window.webContents.on("preload-error", (_, path, error) =>
        console.error("Preload failed:", error.message),
      );
      window.webContents.on("render-process-gone", (_, detail) =>
        console.error("Renderer exited:", detail.reason),
      );
      window.on("close", (event) => {
        if (!quitting && preferences.close_to_tray) {
          event.preventDefault();
          window.hide();
        } else if (!quitting) {
          event.preventDefault();
          app.quit();
        }
      });
      window.once("ready-to-show", () => {
        if (!preferences.start_minimized) window.show();
      });
      tray = new Tray(icon);
      updateTray();
      tray.on("double-click", () => {
        window.show();
        window.focus();
      });
      Menu.setApplicationMenu(null);
      await window.loadFile(resolve(__dirname, "../dist/index.html"));
      console.log("Vertex Batch Studio ready");
    } catch (error) {
      dialog.showErrorBox("工作室启动未完成", error.message);
      app.quit();
    }
  });
  app.on("before-quit", (event) => {
    quitting = true;
    if (!stopped) {
      event.preventDefault();
      void stopBackend().finally(() => {
        stopped = true;
        app.quit();
      });
    }
  });
}
