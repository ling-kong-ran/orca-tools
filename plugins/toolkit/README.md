# Orca Toolkit 1.2.0

一个 Orca 插件统一管理 Accounts、Downloads 和 GPU。**Ctrl+Alt+T** 打开工具集；Ctrl+Alt+D 下载；Ctrl+Alt+G GPU。

- [部署与旧插件迁移](../../docs/toolkit.md)
- [下载模块](../../docs/parallel-download.md)
- [远程账号面板](../../docs/account-switcher.md)
- [GPU 服务与 MCP](../../docs/gpu-bridge.md)

无需 npm install。`modules/` 是内部模块，不单独导入为插件。运行配置在 `%LOCALAPPDATA%/OrcaTools/settings.json`，任务仍保存在原下载目录。模块启动失败不会停止整个 Toolkit。

所有功能在同一管理页内切换：Overview、Accounts、Downloads、Projects、Workflows、Settings。GPU 管理请求由本机 Toolkit 转发至固定回环服务，不向网页传递桥接服务凭据。禁用 Toolkit 入口不会终止独立运行的远程 GPU 渲染服务。

修改 GPU 管理页面后运行 `node scripts/build-toolkit-ui.cjs` 同步插件内的模块片段，再运行 Toolkit 测试。没有前端依赖、iframe 或额外构建服务。更新插件后在 Orca 刷新列表并按提示审核；无需重启电脑、重新登录账号或重启 GPU 服务。
