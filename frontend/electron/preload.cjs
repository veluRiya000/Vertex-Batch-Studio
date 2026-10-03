const { contextBridge, ipcRenderer } = require("electron");
let sequence = 0;
contextBridge.exposeInMainWorld("studio", {
  setPreferences: (value) => ipcRenderer.invoke("studio:preferences", value),
  api: (method, path, body) =>
    ipcRenderer.invoke("studio:api", method, path, body),
  image: (path) => ipcRenderer.invoke("studio:image", path),
  upload: (name, bytes, options) =>
    ipcRenderer.invoke("studio:upload", name, bytes, options),
  chooseDirectory: () => ipcRenderer.invoke("studio:directory"),
  openOutput: (id) => ipcRenderer.invoke("studio:output", id),
  window: (action) => ipcRenderer.send("studio:window", action),
  watch: (id, callback) => {
    const key = "watch-" + ++sequence;
    const handler = (_event, current, snapshot) => {
      if (current === key) callback(snapshot);
    };
    ipcRenderer.on("studio:snapshot", handler);
    ipcRenderer.send("studio:watch", key, id);
    return () => {
      ipcRenderer.removeListener("studio:snapshot", handler);
      ipcRenderer.send("studio:unwatch", key);
    };
  },
});
