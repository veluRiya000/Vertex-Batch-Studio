# Vertex Batch Studio

一个用于 **Google Cloud Vertex AI 图片批量生成**的桌面应用。通过可视化界面管理提示词、参考图和生成任务，完成素材上传、批次提交、进度监控及图片保存。

应用提供 Windows 桌面界面、浏览器开发界面、命令行和本地 HTTP API。默认模型为 `gemini-3.1-flash-image`，默认区域为 `global`。

## 目录

- [主要功能](#主要功能)
- [安装与快速开始](#安装与快速开始)
- [使用流程](#使用流程)
- [配置](#配置)
- [数据与文件管理](#数据与文件管理)
- [从源码运行](#从源码运行)
- [命令行使用](#命令行使用)
- [开发与测试](#开发与测试)
- [构建 Windows 安装包](#构建-windows-安装包)
- [常见问题](#常见问题)
- [贡献与许可](#贡献与许可)

## 主要功能

- **参考图库**：按风格、角色和场景管理常用图片，支持列表与窗格视图、图片预览及拖动排序。
- **批次素材**：导入当前批次专用的临时参考图，保留参考图引用顺序。
- **任务编辑**：设置提示词、模型、画面比例、分辨率、温度和期望图片数量。
- **批量生成**：将任务转换为 JSONL，上传至 Google Cloud Storage，并直接提交 Vertex AI 批次。
- **增量上传**：根据文件内容哈希复用已上传素材，避免重复上传相同内容。
- **进度与恢复**：展示生成队列，监控云端状态，重新启动后恢复未完成批次的本地处理。
- **结果管理**：下载结果分片、保留原始 JSONL、解码所有返回图片，并支持多图预览及自定义输出目录。
- **重试与归档**：复制批次、重试失败任务、重新解码已下载结果，以及归档本地批次。
- **桌面设置**：浅色与深色主题、中英文界面、托盘驻留、开机启动和启动时最小化。

参考图支持 PNG、JPEG 和 WebP。

## 安装与快速开始

### Windows 桌面版

运行 `VertexBatchStudio-Setup-<版本>-x64.exe`，按安装向导完成安装。安装版自带后端运行环境，无需额外安装 Python 或 Node.js。

桌面版从 0.2.0 起使用 Tauri 和系统 WebView2，不再随安装包附带完整浏览器内核。若电脑未安装 WebView2，安装向导会联网下载该运行环境。

首次启动后：

1. 打开左下角 **设置 → Google Cloud 登录**。
2. 填写 Google Cloud 项目 ID 和 Cloud Storage 存储桶名称。
3. 导入服务账号 JSON 密钥，文件名可以自行命名。
4. 在 **关于** 中检查连接。
5. 创建项目，添加任务，再提交批次。

当前安装包未进行代码签名，Windows 可能显示未知发布者提示。

### Google Cloud 准备

云端生成需要具备以下条件：

- 可调用目标模型的 Google Cloud 项目，并已启用 Vertex AI API 和计费。
- 用于保存参考图、输入 JSONL 和生成结果的 Cloud Storage 存储桶。
- 具备批次作业操作及相应存储桶访问权限的凭证。
- Vertex AI 服务代理具备读取输入与参考图、写入结果所需的存储权限。

模型可用性、配额及相关权限由 Google Cloud 决定。**提交批次会产生云端调用及存储费用**；本地编辑任务不会调用生图服务。

## 使用流程

```text
创建项目 → 添加参考图与提示词 → 加入任务 → 提交批次
                                           ↓
                                上传素材并创建云端作业
                                           ↓
                                监控进度 → 下载并保存图片
```

每次点击 **加入任务**，只创建一个任务，对应 JSONL 中的一行。可在同一草稿批次中添加多个任务，点击 **提交批次** 后统一生成。

图库中的图片点击后进入预览；点击图片旁的 **＋** 才会添加到当前输入。拖动图库条目用于调整排列顺序。输入框也支持直接拖入本地图片。

已发送提示词超过五行时自动折叠，可点击“展开全文”或“收起”。右键项目选择 **重命名项目** 可修改显示名称，原有批次目录和云端路径保持不变。输入框上方的 **打开输出目录** 直接打开当前批次的图片保存位置；**设置输出目录** 用于更改保存位置。

右键项目可归档整个项目，归档后从项目列表隐藏，在 **设置 → 归档** 中查看或永久删除。运行中及等待核对云端提交的批次需要先完成或取消。删除仅清理项目的本地文件，保留公共参考图库、外部输出目录和云端对象。

图库图片上的删除按钮适用于列表与窗格视图。待生成任务仍引用的图片会受到保护；已提交任务保有完整参考图快照时，可以从公共图库删除原图，任务及其再次使用仍读取快照。

图片数量可选 1–4。选择多张时，应用会在原始提示词末尾追加生成数量说明，仍然只提交一条请求。**该数量是生成期望，实际返回数量由模型决定**；预览会展示所有返回图片。

开始上传后，当前批次输入被冻结。后续修改或重新生成使用新批次，避免改动正在执行的请求。

## 配置

桌面版可通过设置界面配置云端连接。源码运行或命令行使用时，将根目录下的 `.env.example` 复制为 `.env`：

```powershell
Copy-Item .env.example .env
```

示例配置：

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
GCS_BUCKET=your-storage-bucket
GOOGLE_CLOUD_LOCATION=global
VERTEX_MODEL=gemini-3.1-flash-image
GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json
VBS_DATA_DIR=data
VBS_POLL_SECONDS=30
```

| 配置项 | 用途 | 默认值 |
| --- | --- | --- |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud 项目 ID | 必填 |
| `GCS_BUCKET` | 存储桶名称，不含 `gs://` | 必填 |
| `GOOGLE_CLOUD_LOCATION` | 模型调用区域 | `global` |
| `VERTEX_MODEL` | 图片生成模型 ID | `gemini-3.1-flash-image` |
| `GOOGLE_APPLICATION_CREDENTIALS` | 服务账号 JSON 密钥路径 | 自动检测 `secrets/key.json` |
| `VBS_DATA_DIR` | 本地素材及批次数据目录 | `data` |
| `VBS_POLL_SECONDS` | 云端状态查询间隔，单位秒 | `30` |

配置优先级为 **进程环境变量 → `.env` → 默认值**。相对路径以应用数据根目录为起点；源码模式下，该根目录默认是仓库根目录，也可通过命令行 `--root` 指定。

未指定密钥且不存在 `secrets/key.json` 时，后端使用 Google Application Default Credentials（ADC）。密钥、`.env` 和生成数据应保留在本地，不应提交到仓库。

## 数据与文件管理

Windows 安装版的数据根目录为：

```text
%APPDATA%/VertexBatchStudio/
```

配置、导入的密钥、参考图和批次数据与安装文件分开保存；卸载默认保留用户数据。源码模式默认在仓库根目录保存这些文件。

```text
data/
├── references/
│   ├── characters/
│   ├── scenes/
│   └── styles/
├── batches/
│   └── YYYYMMDD_项目名称/
│       ├── batch.json
│       ├── inputs/
│       ├── custom_refs/
│       ├── outputs/
│       │   ├── raw/
│       │   └── images/
│       └── logs/
└── archive/
```

批次日期使用北京时间，同日同名目录依次追加 `_02`、`_03`，不会覆盖已有批次。批次内部 ID 与文件夹名称分别管理。

默认图片输出目录是批次的 `outputs/images/`，也可选择外部目录。原始响应保留在 `outputs/raw/`，便于重新解码或排查失败结果。

上传仅包含批次引用的素材和输入文件。归档只移动本地批次，不移动或删除云端对象。

## 从源码运行

### 开发环境

- Windows x64；当前安装包及桌面流程在 Windows 上验证。
- Python 3.12 或更新版本，推荐使用 3.12 配合锁定依赖。
- Node.js 22.12 或更新版本，以及 npm。
- 编译桌面版还需要最新稳定版 Rust，以及 Visual Studio Build Tools 的“使用 C++ 的桌面开发”组件和 Windows SDK。

下载或克隆源码后，在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
cd frontend
npm.cmd ci
cd ..
```

配置云端信息后，运行根目录的 `启动界面.cmd`，编译并打开 Tauri 桌面窗口。运行 `预览界面.cmd` 可启动浏览器界面；浏览器模式不提供原生文件夹选择器和系统托盘功能。

也可分别启动后端与前端开发服务器：

```powershell
# 终端一：仓库根目录
.\.venv\Scripts\python.exe -m backend serve

# 终端二：frontend 目录
npm.cmd run dev
```

本地后端仅监听 `127.0.0.1`，默认自动选择空闲端口。连接信息写入 `.runtime/connection.json`，API 使用 `X-VBS-Token` 验证访问；该文件包含本地访问令牌。

## 命令行使用

以下命令在仓库根目录执行。将 `<batch-id>` 替换为 `create` 返回的内部 ID：

```powershell
# 检查本地配置与云端连接
.\.venv\Scripts\python.exe -m backend doctor
.\.venv\Scripts\python.exe -m backend check-cloud

# 创建批次并导入任务
.\.venv\Scripts\python.exe -m backend create "示例项目"
.\.venv\Scripts\python.exe -m backend set-tasks <batch-id> examples/tasks.json
.\.venv\Scripts\python.exe -m backend prepare <batch-id>

# 提交并监控，此处开始调用云端服务
.\.venv\Scripts\python.exe -m backend submit <batch-id>
.\.venv\Scripts\python.exe -m backend watch <batch-id>

# 查看状态与结果
.\.venv\Scripts\python.exe -m backend status <batch-id>
.\.venv\Scripts\python.exe -m backend results <batch-id>
```

`prepare` 仅执行本地校验及输入准备。`check-cloud` 检查连接与权限，不创建生图任务。完整命令可通过 `python -m backend --help` 查看，接口约定见 [API 文档](docs/API.md)。

## 开发与测试

项目由以下部分组成：

| 目录 | 内容 |
| --- | --- |
| `backend/` | Python 工作流、命令行、FastAPI 及云端适配 |
| `frontend/src/` | React 与 TypeScript 界面 |
| `frontend/src-tauri/` | Rust 桌面外壳、托盘及受控 IPC |
| `packaging/` | 后端打包入口与 Windows 构建脚本 |
| `tests/` | 后端自动测试与模拟云端 |
| `examples/` | 示例任务文件 |
| `docs/` | 接口及开发文档 |

运行检查：

```powershell
# 仓库根目录
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v

# frontend 目录
npm.cmd test
npm.cmd run build
```

自动测试使用临时目录和模拟云端，不要求真实密钥，也不会创建收费的生图任务。真实云端联调需要单独准备配置。

## 构建 Windows 安装包

在已安装 Python、Node.js、Rust 和 C++ 构建工具的 Windows 环境中，从仓库根目录执行：

```powershell
python -m venv .venv
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1 -Python .venv/Scripts/python.exe
```

构建脚本使用 PyInstaller 打包后端，并通过 Tauri 生成 x64 NSIS 安装程序。产物保存在 `release/`，个人配置、密钥和批次数据不包含在安装包中。已安装用户的配置和图片目录与旧版一致。

更多说明见 [Windows 打包文档](packaging/README.md)。

## 常见问题

**关闭窗口后任务还会继续吗？**

启用“关闭时最小化到托盘”后，桌面程序与本地监控继续运行。真正退出或关机后，本地处理停止，已经提交的云端任务仍可能继续；再次启动后恢复监控和下载。

**图片数量为什么与选择值不一致？**

数量设置通过提示词表达生成期望，并非服务端强制返回数量。应用会保存实际返回的所有图片。

**下载或解码失败需要重新生成吗？**

已有原始结果可以重新下载或解码，不必重新提交生图请求。失败任务重试会创建新批次，需要另行提交。

**可以在运行中更换 Google Cloud 连接吗？**

需要先完成或取消运行中的批次，再更换项目、存储桶或凭证。

## 贡献与许可

欢迎通过 Issue 报告问题或提出改进，也欢迎提交 Pull Request。问题报告请包含版本、复现步骤和已脱敏的错误信息，避免附上密钥或访问令牌。

当前仓库尚未提供 `LICENSE` 文件；使用及分发授权以维护者声明为准。
