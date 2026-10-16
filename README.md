# Vertex Batch Studio

面向 **Google Cloud Vertex AI Batch** 的 Windows 桌面工作室，将 **批量生图**与 **Harness 本地 Agent** 放在同一个应用中。

[下载安装包](https://github.com/veluRiya000/Vertex-Batch-Studio/releases/tag/v0.3.0-pre.1) · [预发布源码](https://github.com/veluRiya000/Vertex-Batch-Studio/tree/feature/harness-batch) · [反馈问题](https://github.com/veluRiya000/Vertex-Batch-Studio/issues)

> 当前版本为 **0.3.0-pre.1**，属于预发布版本。约 **69.5 MB** 的单个安装器已经包含生图、Harness、Python 后端和 Node 运行环境，无需分别安装组件。最新功能源码位于 `feature/harness-batch` 分支。

## 两种模式

| 模式 | 适合的工作 | 执行方式 |
| --- | --- | --- |
| **生图** | 批量制作图片、使用角色或风格参考图、整理生成结果 | 添加任务，由用户点击提交批次 |
| **Harness** | 处理本地文件、编写文档、修改代码、执行命令 | 开始任务后自动进行“模型 → 工具 → 模型”循环 |

左上角可切换模式。生图使用蓝色界面，Harness 使用暖色界面。切换视图不会关闭正在工作的后台。

Harness 基于 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的会话、工具和审批机制，模型调用接入 Google Cloud Batch，不要求填写 DeepSeek API Key。

## 主要功能

### 批量生图

- **多模型与生成参数**：独立的生图模型目录，设置画面比例、分辨率、数量及模型支持的参数。
- **公共参考图库**：按风格、角色、场景分类；支持列表与窗格切换、拖动排序、预览和删除。点击图片预览，点击 **＋** 才加入当前输入。
- **一次任务，多张图片**：数量可选 **1–4**。选择 4 张时，在同一个云端 Batch 作业中提交 4 条独立生成请求，界面仍归为一条对话，集中展示返回图片。
- **素材复用**：重复生成使用相同的原始提示词、参数和参考图 GCS 地址；同一批次内的参考素材不因张数重复上传。
- **项目管理**：创建、重命名、复制、重试、归档和删除；过长提示词可折叠，创建首个项目时保留已输入的草稿。
- **结果管理**：查看请求完成进度、预览实际返回的全部图片，设置或打开输出目录，保留原始结果以便重新下载、解码。
- **可调布局**：拖动调整侧边栏宽度及参考图库高度，收起项目列表与生成队列。

数量决定请求条数，不保证最终图片数量：审核、失败或缺失结果可能使图片更少；若某条返回多张，也会全部保存。成功结果会保留，失败不会自动补交付费请求。

### Harness Agent

- **工作区与会话**：选择本地工作区，保留对话上下文、附件、工具结果和修改记录。
- **文件与命令工具**：读取、检索、写入、编辑文件，执行 PowerShell，展示文件与交付结果。
- **权限与审批**：复用 DSH 的权限选择、Windows 沙盒及越界操作审批；文件修改包含版本检查，避免覆盖已经变化的内容。
- **附件输入**：支持拖入文件，提供图片输入和受大小限制的文本附件预读，尽量减少模型为读取已上传材料而额外等待的轮次。视频暂不作为模型输入，会标记为不支持并跳过。
- **角色与提示词**：在设置中修改角色提示词，保存后用于后续模型请求。
- **Skills 与 MCP**：支持手动配置；不会默认连接外部 MCP 服务。
- **Batch 活动信息**：显示步骤、等待时间、作业、用量、费用估算及预留金额。
- **运行限额开关**：默认关闭；需要时可启用本地预算、模型请求次数和自定义输出额度。

当前内置的 Harness 模型入口：

| 界面模型 | API 模型 ID |
| --- | --- |
| Gemini 4 Argon | `gemini-4-argon` |
| Gemini 3.8 Flash | `gemini-3.8-flash` |
| Gemini 3.1 Pro Preview | `gemini-3.1-pro-preview` |

这张表描述程序提供的入口；实际可调用性由 Google Cloud 的模型支持、项目权限和区域决定。Harness 与生图各自保存模型选择。

### 桌面与完成提醒

- 浅色 / 深色主题、中英文界面、托盘驻留、开机启动及启动时最小化。
- **Windows 原生完成通知，默认开启**：可选每批完成提醒，或等待同类任务全部结束后提醒。
- 生图与 Harness 分别统计，互不阻塞；可独立设置提醒范围及是否提醒失败。
- 三种内置提示音，可试听，也可导入 WAV / MP3 自定义声音。
- 生图和 Harness 共用 Google Cloud 连接设置，项目、存储桶和凭证字段旁提供控制台入口。

## 下载与安装

1. 打开 [0.3.0-pre.1 发布页](https://github.com/veluRiya000/Vertex-Batch-Studio/releases/tag/v0.3.0-pre.1)。
2. 下载 `VertexBatchStudio-Setup-0.3.0-pre.1-x64.exe`。这一份已经包含两种模式。
3. 退出正在运行的旧版本，再运行安装器。
4. 启动程序，配置 Google Cloud 后选择需要的模式。

面向 Windows x64。安装版不要求另外安装 Python、Node.js 或 Rust；使用系统 WebView2，缺少时安装向导会下载运行环境。安装包未签名。

发布附件提供 SHA-256 校验值与构建信息。个人会话、图片、密钥和开发数据不包含在安装包中，也不会随安装自动导入。

## Google Cloud 准备

使用云端模型前，需要：

1. 准备已启用计费和 Vertex AI API、并可访问目标模型的 Google Cloud 项目。
2. **先创建 Cloud Storage 存储桶**，用于保存参考素材、Batch 输入及返回结果。
3. 准备具备相关 Batch 操作和存储桶访问权限的服务账号 JSON 密钥；Vertex AI 服务代理也需要访问输入与结果对象的权限。
4. 在 **设置 → Google Cloud 登录** 中填写项目 ID、存储桶名称，并导入 JSON 密钥。密钥文件不必叫 `key.json`。
5. 点击 **检查连接**。Google Cloud 字段旁的跳转按钮可以打开相应控制台页面。

生图与 Harness 共用这份连接配置。提交请求会产生云端模型调用及存储费用；本地编辑草稿不会自动调用生成服务。

## 使用流程

### 生图

```text
新建项目 → 输入提示词、添加参考图 → 选择模型和参数 → 加入任务
                                                        ↓
                                             手动点击“提交批次”
                                                        ↓
                                             等待 → 查看、保存图片
```

“加入任务”创建一个界面任务。同一批次可包含多个任务；每个任务按所选张数展开为对应数量的云端请求。比如两个各生成 4 张的任务，界面显示两条对话，提交的 JSONL 包含 8 条请求。

开始上传后，输入保持冻结。需要修改或再次生成时使用新批次。右键项目可以重命名或归档；归档项目位于 **设置 → 归档**，可在其中删除本地项目。

### Harness

```text
切换 Harness → 选择工作区 → 输入任务、添加附件 → 选择模型与权限 → 开始
                                                                       ↓
                                             Batch 返回 → 本地工具 / 审批
                                                                       ↓
                                               必要时继续下一轮 → 交付
```

模型生成请求全部走 Google Cloud Batch，不自动切换实时 API。状态、工具日志和改动会持续更新，模型正文需要等当前 Batch 结果返回；它不是逐 Token 的实时聊天。

尽量在任务中一次说明目标、输入材料、输出位置和验收要求。存在依赖的工具步骤仍可能需要多轮请求，每轮都会再次等待 Batch。

权限设置与运行限额是两件事：关闭本地运行限额不会扩大文件或命令权限，也不会解除云端模型、输出长度或计费方面的限制。

## 数据与恢复

Windows 安装版使用独立的用户数据目录：

```text
%APPDATA%/VertexBatchStudio/
├── settings.json             # 外观、桌面与提醒设置
├── secrets/                  # 导入的凭证
├── data/
│   ├── references/           # 公共参考图库
│   ├── batches/              # 生图输入、原始结果、图片和日志
│   ├── archive/              # 已归档的生图批次
│   ├── harness/              # 会话、附件、调度账本与原始模型结果
│   └── notifications/        # 提示音与提醒观察记录
└── .runtime/                 # 本机连接与启动配置
```

程序和内置 Harness 运行文件位于安装目录；可写配置与用户数据分开保存。默认图片输出在批次的 `outputs/images/`，也可在界面选择外部目录。卸载默认保留用户数据。

- **缩到托盘**：后台继续工作，也可发送完成提醒。
- **真正退出或关机**：本地工具和下载监控停止，已提交的云端作业可能继续。
- **重新启动**：生图可恢复监控、下载和解码；Harness 可继续核对已提交请求，但不保证被中断的整个 Agent 轮次无缝恢复。有副作用的操作不应直接盲目重跑。
- **归档与删除**：生图归档管理本地项目，不删除云端对象；外部输出目录和公共参考图库另行管理。

## 费用、限额与使用边界

- 费用显示区分**估算用量费用**与**提交前预留**；预留不代表已经扣款，赠金、优惠及最终费用以 Cloud Billing 为准。
- 本地运行限额默认关闭。启用后，预算与模型请求次数会约束后续提交；已经提交的输入不会被重新改写。
- Argon 仅在云端返回有效续传令牌时尝试继续长输出。没有有效令牌、达到云端限制或发生错误时会停止并保留原始结果；不能保证一次得到百万 Token 输出。
- 截断或损坏的工具参数不会直接执行。必要的本地读取、验证或审批也不会因为希望减少 Batch 轮次而被跳过。
- Windows 沙盒主要约束文件写入，不是虚拟机，也不全面隔离读取、网络与进程；MCP 不会自动获得同样的隔离。
- 当前为预发布版本，已做基础离线与打包启动检查，完整云端、异常恢复和覆盖升级场景仍需继续验证。

## 从源码运行

### 获取当前预发布源码

```powershell
git clone --branch feature/harness-batch --recurse-submodules https://github.com/veluRiya000/Vertex-Batch-Studio.git
cd Vertex-Batch-Studio
```

已有克隆可执行 `git submodule update --init --recursive`，取得固定版本的 DSH。直接下载 GitHub 源码 ZIP 不会自动补齐子模块。

### 环境与依赖

- Python 3.12，配合 `requirements.lock.txt`。
- 前端使用 Node.js 与 npm；Harness 组件构建脚本固定使用 **Node.js 24.18.0**，上游依赖按其锁文件安装。
- 编译桌面版还需要兼容 `Cargo.toml` 的 Rust 工具链、Visual Studio C++ 构建工具和 Windows SDK。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
cd frontend
npm.cmd ci
cd ..
```

源码模式可在 `.env` 配置云端连接，示例：

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
GCS_BUCKET=your-storage-bucket
GOOGLE_CLOUD_LOCATION=global
VERTEX_MODEL=gemini-3.1-flash-image
GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json
VBS_DATA_DIR=data
VBS_POLL_SECONDS=30
```

`VERTEX_MODEL` 配置生图默认模型，Harness 有独立模型选择。不要把 `.env`、密钥、会话或生成结果提交到 Git。

只运行生图前后端，可使用两个终端：

```powershell
# 终端一：仓库根目录
.\.venv\Scripts\python.exe -m backend serve

# 终端二：frontend 目录
npm.cmd run dev
```

桌面开发模式在 `frontend/` 运行 `npm.cmd run desktop`。使用 Harness 前，需按 [组件构建说明](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/HARNESS_COMPONENT.md) 构建固定版本的上游并生成 `harness/component/`；安装版无需这些开发步骤。

### 构建安装包

准备好 `harness/component/` 后，在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1 -Python .venv/Scripts/python.exe
```

产物位于 `release/`。合并安装器包含生图和 Harness，构建目录、依赖缓存、开发数据和凭证不随 Git 提交。构建会重新生成较大的依赖与编译缓存，它们不等于安装包大小。

### 项目结构与测试

| 目录 | 内容 |
| --- | --- |
| `backend/` | FastAPI、图片批次、Harness Batch 调度、费用与完成提醒 |
| `frontend/src/` | 生图界面、模式切换与公共设置 |
| `frontend/src-tauri/` | 桌面窗口、托盘及原生接口 |
| `harness/plugins/` | Batch 模型适配、提示词策略与 Harness 主题插件 |
| `harness/upstream/` | 固定版本的 DSH 子模块 |
| `packaging/` | 后端冻结与合并安装器构建 |
| `tests/`、`docs/` | 后端测试及功能说明 |

```powershell
# 仓库根目录：使用临时数据和模拟云端的后端测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v

# frontend 目录
npm.cmd test
npm.cmd run build
```

命令行入口仍可使用，例如 `python -m backend --help`；接口与命令约定见下方文档。

## 文档

- [本地 API 与生图流程](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/API.md)
- [Harness 功能与权限](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/HARNESS_FEATURES.md)
- [模型入口](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/HARNESS_MODELS.md)
- [长输出续传](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/HARNESS_CONTINUATION.md)
- [完成提醒](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/docs/COMPLETION_NOTIFICATIONS.md)
- [Windows 打包](https://github.com/veluRiya000/Vertex-Batch-Studio/blob/feature/harness-batch/packaging/README.md)

## 反馈与许可

欢迎通过 Issue 报告问题，提供版本、所用模式、复现步骤和脱敏日志。请勿上传服务账号密钥、访问令牌或未经处理的私人会话。改进可提交至当前开发分支。

当前仓库尚未提供项目级 `LICENSE` 文件，使用及分发授权以维护者声明为准。

DSH 上游固定为 `d743267388641bc76f17c45ce8b4c231aed1d32c`，使用 MIT 许可证；这不自动代表本项目其余代码也采用 MIT。运行包保留相关第三方许可证和 Node 许可说明。Google Cloud、Vertex AI、Gemini 为其所属公司的产品或商标，本项目并非 Google 官方产品。
