import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const connectionFile =
  process.env.VBS_CONNECTION_FILE ||
  resolve(import.meta.dirname, "../.runtime/connection.json");
let lastConnection: { url: string; token: string } | undefined;
const connection = () => {
  let info;
  try {
    info = JSON.parse(readFileSync(connectionFile, "utf8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT" && lastConnection)
      return lastConnection;
    throw error;
  }
  if (
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(info.url) ||
    typeof info.token !== "string" ||
    !info.token
  )
    throw new Error("本机后端连接记录无效");
  return (lastConnection = info);
};

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: connection().url,
        rewrite: (path) => path.replace(/^\/api/, ""),
        configure(proxy, options) {
          // A backend restart can change its port. Refresh the target before each request.
          options.bypass = (_request, _response, requestOptions) => {
            const info = connection();
            options.target = info.url;
            requestOptions.target = info.url;
          };
          proxy.on("proxyReq", (proxyReq, request) => {
            const origin = request.headers.origin;
            const expected = `http://${request.headers.host}`;
            if (origin && origin !== expected) {
              proxyReq.destroy(new Error("仅接受本机界面请求"));
              return;
            }
            const info = connection();
            proxyReq.setHeader("X-VBS-Token", info.token);
          });
        },
      },
    },
  },
});
