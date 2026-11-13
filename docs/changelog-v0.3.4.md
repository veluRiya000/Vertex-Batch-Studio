# v0.3.4 · 连接恢复与参考图库改进

本次更新改善长期后台运行时的云端连接恢复，并补充参考图库导入与提示词操作。

## 连接恢复

- 网络、代理或连接池异常后退役失效的云端客户端，后续请求重新建立客户端，无需重新保存连接配置。
- 等正在使用旧客户端的请求退出后才关闭连接，避免影响并发上传与查询；过期检查结果不会清除新客户端。
- 连接检查记录底层异常类型和脱敏消息，隐藏私钥、Token、代理认证与签名 URL 参数。
- EOF、连接重置等网络错误显示为“网络连接中断，请检查网络或代理后重试”。
- 保留批次原有恢复流程，客户端重建不会自动重放创建批次的请求。

## 参考图库与界面

- 在“添加参考图分类”弹窗中选择“导入文件夹”，自动使用文件夹名称；确认添加后才复制图片，取消不留下分类或图片。
- 只导入当前文件夹中的 PNG、JPEG、WebP 图片，显示分批导入进度，并跳过无效图片。
- 减少导入、删除时重复检查整个图库的开销，多张图片导入时逐批更新显示。
- 修复列表模式长文件名挤出添加、删除按钮的问题，并恢复将参考图拖进输入框的操作。
- 提示词旁新增独立“复制”按钮；“再次使用”采用向下箭头图标。
- “关于”窗口显示灰色小号构建版本，版本号自动随打包更新。

## 安装

- Windows x64 合并安装包：`VertexBatchStudio-Setup-0.3.4-x64.exe`，约 69.5 MB。
- 包含生图、Harness、Python 后端与 Node.js 运行时；继续使用系统 WebView2。
- 支持覆盖升级，维护页面默认添加或重新安装组件；用户配置与数据继续保存在独立目录。

---

## English

Version 0.3.4 improves cloud connection recovery during long-running desktop sessions and adds reference-library and prompt controls.

- Retire broken cloud clients after transport failures and rebuild them for subsequent requests. In-flight calls finish before retired clients close; stale probes cannot replace a newer client.
- Log underlying exception types with private keys, tokens, proxy credentials and signed URL parameters redacted.
- Show a readable network-interruption message for EOF and connection-reset errors. Client recovery does not replay batch-creation requests.
- Import images from a folder through the existing Add Category dialog. The folder name becomes the default category name; cancelling before confirmation leaves no imported data.
- Import supported images from the selected folder only, show progress, and skip invalid images.
- Reduce repeated library inspection, keep list actions within narrow sidebars, and restore drag-to-composer reference attachment.
- Add a dedicated Copy Prompt button, update the Reuse icon, and show the build version in About.
- The combined Windows x64 installer supports in-place upgrades and retains user data separately.
