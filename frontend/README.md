# Vertex Batch Studio Frontend

基于 React、TypeScript 和 Vite 的图片批次工作室界面，通过 Electron 提供 Windows 桌面功能。

## 开发

需要 Node.js 22.12+。在仓库根目录完成 Python 环境配置，并先启动后端：

```powershell
.\.venv\Scripts\python.exe -m backend serve
```

在本目录运行：

```powershell
npm.cmd ci
npm.cmd run dev
```

开发服务器默认使用 `http://127.0.0.1:5173`，通过根目录的 `.runtime/connection.json` 获取后端地址和访问令牌。该文件应保留在本地。

## 桌面运行

安装依赖后，在本目录执行：

```powershell
npm.cmd run build
npm.cmd run desktop
```

也可运行仓库根目录的 `启动界面.cmd`。Electron 会连接或启动本地后端，并提供文件夹选择、托盘和开机启动等系统功能。

主进程持有后端访问令牌，通过受控 IPC 转发界面操作；渲染进程启用上下文隔离和沙箱。

## 测试与构建

```powershell
npm.cmd test
npm.cmd run build
```

Windows 安装包需先打包 Python 后端，请使用仓库根目录的 [Windows 构建脚本](../packaging/README.md)。

## 代码结构

- `src/`：界面、状态、API 客户端及组件测试。
- `electron/`：桌面主进程、预加载脚本和应用图标。
- `scripts/`：本地预览启动工具。
- `dist/`：生成的前端构建产物，不提交到 Git。

应用使用说明、云端配置及数据目录约定见 [项目 README](../README.md)。
