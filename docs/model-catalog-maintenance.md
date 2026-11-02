# 维护生图模型目录

维护文件：`backend/model-catalog.json`。这是数据文件，不执行任何下载代码。

## 更新名单，不重新构建软件

1. 在 Google Cloud 批量推理界面核对模型 ID、所选区域，以及必要的图片参数。
2. 编辑 JSON 中的 `models`；可复制相近条目再修改。`enabled: false` 可停用条目，或直接从名单删除。
3. 更新 `version`（例如 `2026.11.03.2`）和 `updated_at`（`YYYY-MM-DD`）。保持 JSON 有效。
4. 将该文件发布到仓库的 `master` 分支。客户端固定读取：
   `https://raw.githubusercontent.com/veluRiya000/Vertex-Batch-Studio/master/backend/model-catalog.json`
5. 在生图输入栏模型选择旁点击“更新模型目录”。无需重启或重新安装，不影响已经提交的批次。

客户端优先自动读取 Google 官方目录；自动读取失败后读取开发者在线名单，再使用本地成功缓存，最后使用安装包附带的同名名单。在线名单首次发布前，客户端仍能使用安装包名单。本次改动没有自动推送任何文件到 GitHub。

## 字段

- `id`：Google Cloud 实际模型 ID，不能填写显示名。
- `label`：界面名称。
- `regions`：可用区域，例如 `["global"]`；不要将单个项目访问权限当成所有账号都有权限。
- `source_url`：该模型的 Google Cloud 文档地址。
- `supports_image_size`、`aspect_ratios`、`max_references`、`unsupported_parameters`：客户端已有的参数能力描述。
- `batch_image_sizes`：当前 Batch 生图使用 `["1K"]`。
- `retirement_date`：已确认的退役日期，未知时为 `null`。
- `enabled`：是否显示，默认 `true`。

名单限 100 个模型，下载限 1 MB；结构错误时保留可用目录，不将空白网页解释为模型全部退役。不通过创建付费作业验证名单。

## 数据保存与故障恢复

新解码图片固定先保存到各批次的 `outputs/images/`，再复制到用户指定的输出目录。云端原始 JSONL（含 base64）保存在 `outputs/raw/`。外部复制失败不会删除项目副本；可用“重新解码”再次导出。旧项目可通过重新解码补齐项目副本。

归档列表的文件夹按钮打开该项目最新批次的真实目录；多批次项目可展开“全部批次文件夹”。重命名只改显示名称，不重命名磁盘目录或云端前缀。

连接检查按稳定的连接配置去重；刷新配置不会每五秒创建新检查。提交前凭证刷新失败可安全重试；创建请求结果不明时仍禁止自动重复创建，十分钟无匹配后停止自动核对，可手动刷新再次查找。该状态不是云端已经取消。
