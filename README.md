# VertexBatchStudio

浏览器界面已可操作。双击根目录的 **`预览界面.cmd`**，自动启动后端、前端并打开浏览器。当前预览地址为 `http://127.0.0.1:5173`。关闭浏览器后，本地监控继续运行；停止后端使用 `停止后端.cmd`。

界面支持公共参考图库、本批次临时参考图、单条任务编辑、参数选择、提交与实时队列，以及结果多图预览。每次点击“加入任务”只添加一个任务；点击“提交批次”才会上传并调用真实 Vertex AI。提交后继续写提示词会创建同一项目的新一轮，不修改已提交输入。

参考图库右上可切换列表或窗格。点击条目预览，点击图片旁的“＋”加入当前输入框；拖动条目调整排列顺序，重开后保留。风格、人设、场景分别保存顺序，图片原文件路径不变。

浏览器无法直接弹出 Windows 文件夹选择器：输出目录在弹窗中填写绝对路径，结果区可复制保存路径。左上“关于”查看连接信息；左下“设置”切换主题和语言，并在 Google Cloud 登录页修改项目、桶名或导入任意文件名的服务账号 JSON 密钥。改动即时生效并写入 `.env`，旧密钥保留；运行中的批次完成或取消后才能更换连接。

双击 **`启动界面.cmd`** 可打开 Electron 桌面窗口，自动连接或启动本机后端。默认关闭后驻留托盘；设置里可关闭该行为，也可启用开机自启动和启动时最小化至托盘。选择“退出工作室”会正常停止后端。主题、语言及侧栏宽度保存在本地 `settings.json`；拖动侧栏右边缘调宽，左下按钮快速收起或展开。桌面模式可使用 Windows 文件夹选择器和“打开输出文件夹”。运行组件目录的读取权限已按用户授权调整，沙箱保持开启；桌面启动已验证，托盘、开机启动、目录选择等系统交互仍需实际试用验证。尚未打包独立 EXE。

本地 Vertex AI 图片批次工作室。Python 工作流、命令行、FastAPI、React 界面和 Electron 桌面入口共用同一份批次数据。

默认模型 `gemini-3.1-flash-image`，区域 `global`。后台运行时每 30 秒检查云端任务，下载所有可用结果分片，保存原始 JSONL 并解码图片。

## 启动

在本项目目录打开终端，使用项目自己的解释器：

```powershell
.\.venv\Scripts\python.exe -m backend doctor
.\.venv\Scripts\python.exe -m backend serve
```

也可以双击 `检查配置.cmd` 或 `启动后端.cmd`。已运行的后端可通过 `停止后端.cmd` 正常退出；这不会取消云端生图任务。

服务自动选择空闲端口，只监听 `127.0.0.1`。连接地址和随机令牌写入 `.runtime/connection.json`，正常退出后删除。所有接口需要 `X-VBS-Token` 请求头，包括 OpenAPI 接口。令牌不放在 URL 中。

后台程序运行时会恢复此前未完成的任务。此阶段关闭终端会停止本地监控，已提交的云端任务继续执行；再次启动会恢复。窗口隐藏到托盘的行为属于后续 Electron 阶段。

## 配置

你已经填写的 `.env` 和密钥保持原样。配置值的优先级为进程环境变量、`.env`、默认值。相对路径都以软件根目录为起点。

关键配置：`GOOGLE_CLOUD_PROJECT`、`GCS_BUCKET`、`GOOGLE_APPLICATION_CREDENTIALS`。项目 ID 与你填写的批次项目名称是两个概念。凭证文件只在云端操作时加载，离线整理任务不需要访问 Google。

只读检查连接，不上传、不创建任务：

```powershell
.\.venv\Scripts\python.exe -m backend check-cloud
```

它检查调用账号能否列出任务、读取桶，以及拥有的桶权限；Google 服务代理的参考图读取和输出写入权限仍需首次真实生图确认。

## 从命令行跑一个批次

下列命令中的 `<批次ID>` 替换成 `create` 返回的 `id`，不是目录名称。

```powershell
.\.venv\Scripts\python.exe -m backend create "夏日祭分镜"
.\.venv\Scripts\python.exe -m backend set-tasks <批次ID> examples/tasks.json
.\.venv\Scripts\python.exe -m backend prepare <批次ID>
```

`prepare` 只做本地校验、参考图快照和 JSONL 编写，可查看批次目录内的 `inputs/prompts.jsonl`。

准备好后提交，并监控：

```powershell
.\.venv\Scripts\python.exe -m backend submit <批次ID>
.\.venv\Scripts\python.exe -m backend watch <批次ID>
```

`submit` 会上传本批次引用的参考图与输入文件，并创建云端任务。这一步开始调用收费的生图服务；示例文件包含两条任务。提交后也可以保持 `serve` 运行，让它自动监控。

查看状态或输出：

```powershell
.\.venv\Scripts\python.exe -m backend status <批次ID>
.\.venv\Scripts\python.exe -m backend results <批次ID>
```

## 导入与使用参考图

```powershell
.\.venv\Scripts\python.exe -m backend import-ref "D:\图片\画风.png" --category styles
.\.venv\Scripts\python.exe -m backend import-ref "D:\图片\姿势.png" --batch <批次ID>
.\.venv\Scripts\python.exe -m backend references --batch <批次ID>
```

导入返回受管理的 `path`，例如 `references/styles/画风.png`。将它放进任务的 `refs` 列表，顺序就是提示词里的参考图顺序。

```json
{
  "name": "人物近景",
  "prompt": "采用参考图一中的画风，绘制人物近景。",
  "refs": ["references/styles/画风.png"],
  "aspect_ratio": "16:9",
  "image_size": "1K",
  "temperature": 0.35
}
```

公共素材分类为 `characters`、`scenes`、`styles`。临时素材复制到当前批次的 `custom_refs`。第一版支持 PNG、JPEG、WebP，检查实际文件格式；同名不同图不会覆盖。

提交前保留参考图快照。云端图片文件名包含完整内容哈希，内容不变可复用；相同大小但不同内容也会上传新版本。上传清单只包含引用素材和该批次输入，凭证、代码、日志、归档和解码图片不回传。

旧的 `prompts.jsonl` 可以通过 `import-jsonl <批次ID> <文件路径>` 导入。仅支持原脚本使用的“单轮 user、提示词在前、随后参考图”结构，兼容 snake_case 与 camelCase；不执行旧 Python 脚本。远程参考图必须位于当前桶中，原 URI 会保留。

## 批次目录与恢复

```text
data/
├── references/{characters,scenes,styles}/
├── batches/日期_项目名称/
│   ├── batch.json
│   ├── inputs/{tasks.json,prompts.jsonl,manifest.json,assets/}
│   ├── custom_refs/
│   ├── outputs/{raw/,images/,results.json}
│   └── logs/events.jsonl
└── archive/
```

日期使用北京时间。同日同名自动加 `_02`、`_03`，归档名称也保持占用。内部 ID 留在 JSON 内。你前面练习创建的五字段 `batch.json` 会兼容读取，旧文件不会在读取时被覆盖；缺少 `tasks.json` 的草稿视为空任务。

输入从开始上传起冻结；已提交批次不能修改任务。重新生成使用 `clone`，只重新生成失败项使用 `retry`，都建立新批次，且不会自动提交。

```powershell
.\.venv\Scripts\python.exe -m backend retry <批次ID>
.\.venv\Scripts\python.exe -m backend clone <批次ID>
.\.venv\Scripts\python.exe -m backend set-output <批次ID> "D:\生成图片"
.\.venv\Scripts\python.exe -m backend extract <批次ID>
.\.venv\Scripts\python.exe -m backend cancel <批次ID>
.\.venv\Scripts\python.exe -m backend archive <批次ID>
```

- `extract` 从已下载原始结果重新导出，不重新生成；导出失败时可更换目录后重试。
- 网络失败保留已完成分片的下载记录；重开后按任务编号继续。下载缓存损坏会重新下载。
- 提交超时会进入 `submission_unknown`，程序核对云端记录，不会盲目再次创建。若多条任务对应同一批次，可用 `attach <批次ID> <完整云端任务编号>` 选择。
- 结果按回传请求匹配，处理全部分片和图片，保留错误与缺失结果。相同请求按同组及固定任务 ID 顺序分配；不依赖云端行顺序。
- 归档只移动本地批次，不移动云端对象；内部默认导出图片的路径也会更新。外部导出目录保持原位。

## 开发与测试

项目 `.venv` 已安装本次使用的依赖。另一台 Windows/Python 3.12 环境可以按锁定版本安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

所有自动测试使用临时目录和模拟云端，不读取真实密钥，不创建收费任务。包含真实本机 HTTP 服务的启动、令牌验证和正常关闭测试。现有 `backend/batches.py` 是你亲手写的教学脚本，可保留；正式流程使用 `Repository` 与 `Studio`。

接口列表与数据约定见 `docs/API.md`，实际完成和待完成的验收见 `docs/VALIDATION.md`。主要模块为配置、仓库、素材、JSONL、云端适配、结果提取和工作流；核心可以直接从 Python 调用，也可以通过命令行或 HTTP 使用。
