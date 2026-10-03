# 本地后端接口

启动命令：`python -m backend serve`。接口前缀为 `.runtime/connection.json` 中的 `url`，每次启动随机生成令牌。请求头：`X-VBS-Token: <token>`。

这是单用户、本机接口，未开放 CORS。浏览器开发界面通过 Vite 的本机代理访问，桌面界面通过受限 IPC 转发；令牌留在代理或主进程中，不写进页面。

## 素材

| 请求 | 行为 |
|---|---|
| `GET /health` | 本地状态与配置是否已填写 |
| `GET /config` | 供界面显示的配置，不含密钥内容、令牌或凭证文件路径 |
| `GET /preferences` | 读取本地主题、语言、桌面行为与侧栏宽度 |
| `PUT /preferences` | 保存完整偏好；桌面端通过受限 IPC 同步开机启动和托盘设置 |
| `PUT /cloud/configuration` | 保存 project、bucket，可选 key_json 和 credential_filename；验证后复制到 secrets，不覆盖旧密钥 |
| `POST /cloud/check` | 只读检查已有连接与权限，不创建生图任务 |
| `GET /references?batch_id=...` | 公共素材及指定批次临时素材 |
| `PUT /references/order` | 保存某分类的显示顺序；body 为 category 与完整 paths 列表；重复、跨分类或过期列表被拒绝 |
| `POST /references/import` | 从选中的本地文件导入图片 |
| `POST /references/upload?name=...&category=...` | 接收浏览器图片二进制；category 或 batch_id 必填且互斥；最大 30 MB |
| `GET /references/file?path=...&batch_id=...` | 预览受管理参考图 |

导入公共素材：`{"source":"D:/图片/风格.png","category":"styles"}`。

导入临时素材：`{"source":"D:/图片/姿势.png","batch_id":"<id>"}`。

两个目标互斥。返回的 `path` 用于任务 `refs`；图片只在后端创建上传清单时转换成 GCS URI。

## 批次与任务

| 请求 | 行为 |
|---|---|
| `PUT /workspaces/{workspace_id}` | 重命名项目所有批次的显示名称；body 为 `{"project_name":"新名称"}`，目录、冻结请求和云端路径保持不变 |
| `POST /batches` | 创建批次，返回内部 ID 和完整状态 |
| `GET /batches` | 按创建时间列出批次，包含归档 |
| `GET /batches/{id}` | 查询批次状态、错误与完成数量 |
| `GET /batches/{id}/tasks` | 读取任务 |
| `PUT /batches/{id}/tasks` | 替换整个草稿任务列表 |
| `POST /batches/{id}/tasks` | 追加一个任务；自动创建任务 ID 和创建时间 |
| `DELETE /batches/{id}/tasks/{task_id}` | 删除尚未提交的任务 |
| `PUT /batches/{id}/tasks/{task_id}` | 修改单条任务并保留其 ID |
| `POST /batches/{id}/import-jsonl` | 导入旧 JSONL |
| `PUT /batches/{id}/output-directory` | 设置外部导出目录；`null` 恢复批次内默认目录 |
| `POST /batches/{id}/prepare` | 本地校验、快照、生成提交文件 |
| `POST /batches/{id}/submit` | 后台上传并提交，返回 202 |
| `POST /batches/{id}/poll` | 立即安排一次后台检查，返回 202 |
| `POST /batches/{id}/extract` | 从本地结果重新导出，返回 202 |
| `POST /batches/{id}/cancel` | 请求取消云端任务，仍收集已有结果 |
| `POST /batches/{id}/attach` | 核对后关联指定云端任务 |
| `POST /batches/{id}/retry` | 创建只包含失败/缺失项的新批次 |
| `POST /batches/{id}/clone` | 创建包含全部任务的新批次 |
| `POST /batches/{id}/archive` | 归档本地批次 |
| `GET /batches/{id}/results` | 任务结果、错误及本地图片路径 |
| `GET /batches/{id}/images/{task_id}/{index}` | 图片预览；index 从 0 开始 |
| `GET /batches/{id}/events` | SSE 状态和结果快照 |
| `POST /shutdown` | 正常关闭后端 |

创建请求：`{"project_name":"夏日祭分镜","image_output_dir":null}`。

任务替换请求：

```json
{
  "tasks": [
    {
      "name": "全景",
      "prompt": "黄昏的夏日祭街道，动画风格。",
      "refs": [],
      "aspect_ratio": "16:9",
      "image_size": "1K",
      "image_count": 1
    }
  ]
}
```

可选字段 `temperature` 为 0–2；不填时交给模型默认值。`generation_config` 可保留旧任务的其他生成配置，输出模态与图片参数由显式任务字段统一设置。宽高比、分辨率和参考图数量在本地检查。

`image_count` 是 1–4 的整数，默认 1，旧任务兼容为 1。`prompt` 始终保存原文；生成 JSONL 时，2–4 张在原文末尾追加空行和 `请生成{数量}张独立图片，每张单独输出，不要将多张图片拼成一张。`，1 张不追加。每条任务仍只生成一行 JSONL，不修改 `candidateCount`，结果指纹使用实际提交文本。数量代表期望，返回图片全部保留；少图不会自动重提。

批量替换时可保留当前批次已有任务的 `id`，用于重排任务而不改变编号；新增任务不填 `id`，由后端分配。单条编辑始终保留原 ID。重复 ID 或其他批次的 ID 会被拒绝。

JSONL 导入请求：`{"source":"D:/某个批次/prompts.jsonl"}`。

导出目录请求：`{"path":"D:/生成图片"}`。

关联任务请求：`{"job_name":"projects/.../locations/global/batchPredictionJobs/..."}`。

202 返回 `{"queued":true,"batch_id":"..."}` 表示操作已排队。若同批次已有后台操作，`queued` 为 false；查看状态即可。后台失败记录在 `last_error`，不会只在终端显示。

批次 `phase`：`draft`、`prepared`、`uploading`、`upload_failed`、`submitting`、`submission_unknown`、`submission_failed`、`monitoring`、`downloading`、`paused`、`completed`、`completed_with_errors`、`failed`、`cancelled`。它与 Google 的 `cloud_state` 分开保存。

结果中每条任务状态为 `pending`、`succeeded`、`error` 或 `missing`；一条任务可能有多张图片。原始 JSONL 始终保留，不能只根据“云端成功”推断所有图片已导出。

## SSE 与错误

使用支持自定义请求头的流式客户端读取 SSE，不能把令牌放进 URL。事件名为 `snapshot`，数据包含 `batch` 和 `results`，空闲时发送 keepalive 注释。连接或重连均先发送完整快照，完成后关闭流。

HTTP 状态：401 令牌无效，403 非本机连接，404 资源不存在，409 批次正被其他操作处理，422 输入模型校验失败，400 状态或业务校验失败。

OpenAPI 为 `/openapi.json`，也需要令牌。云端凭证、密钥内容和 Base64 原始图像不会放进 API 返回值。
