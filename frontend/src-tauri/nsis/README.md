# 安装器维护页面

`installer.nsi` 基于 Tauri CLI v2.12.1，固定上游提交 `30da1fd6e17de6107ecc850c95dfb16b5729f2dd`，许可为 MIT OR Apache-2.0。

原文件：https://github.com/tauri-apps/tauri/blob/30da1fd6e17de6107ecc850c95dfb16b5729f2dd/crates/tauri-bundler/src/bundle/windows/nsis/installer.nsi

本地仅修改 NSIS 维护/升级分支：

- 同版本和升级到新版均显示“添加/重新安装组件 / 卸载应用”。升级说明显示真实已安装版本。
- 默认添加/重新安装直接覆盖程序文件，不调用旧卸载器。
- 用户明确选择卸载时执行旧卸载器，完成后退出安装向导，不继续安装。
- 原有进程清理 hooks、数据存储、MSI迁移及降级处理保留。

以后更新 Tauri CLI 时，需要比对这个固定模板与新的上游模板，再更新维护分支。不能仅修改 `hooks.nsh` 或版本号来模拟维护页面。
