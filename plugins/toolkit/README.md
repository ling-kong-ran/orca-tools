# Orca Toolkit 1.0.0

一个 Orca 插件统一管理 Accounts、Downloads 和 GPU。**Ctrl+Alt+T** 打开工具集；Ctrl+Alt+D 下载；Ctrl+Alt+G GPU。

- [部署与旧插件迁移](../../docs/toolkit.md)
- [下载模块](../../docs/parallel-download.md)
- [远程账号面板](../../docs/account-switcher.md)
- [GPU 服务与 MCP](../../docs/gpu-bridge.md)

无需 npm install。`modules/` 是内部模块，不单独导入为插件。运行配置在 `%LOCALAPPDATA%/OrcaTools/settings.json`，任务仍保存在原下载目录。模块启动失败不会停止整个 Toolkit。

账号操作打开 VPS 的回环面板，GPU 操作打开本机桥接管理页；下载页面直接由 Toolkit 18774 提供。禁用 Toolkit 入口不会终止独立运行的远程 GPU 渲染服务。
