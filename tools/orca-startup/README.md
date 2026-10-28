# Orca Startup

Windows 登录助手，每 15 秒等待 Orca 并激活已审核启用的 Toolkit，不弹出管理页，不自动批准新版本。即使 Toolkit 管理页仍在线，也会单独检查 GPU Bridge 的私网监听和本机管理页；失联时通过已获授权的 `toolkit.gpu` 命令重新启动服务。失败后的拉起间隔至少 60 秒，不中断正在运行的渲染，不重提历史任务。禁用 GPU 模块或插件后停止恢复尝试。

此助手独立于插件安装目录，更新它不会改变 Toolkit 的授权指纹。Toolkit 当前包含快捷键贡献，Orca 会把安装内容身份加入授权指纹，因此修改 Toolkit 插件代码后仍需在 Orca 重新确认。

安装：`node install.cjs`。首次立即启动：`node "%LOCALAPPDATA%/OrcaLocalTools/bootstrap.cjs"`（CMD；PowerShell 使用 `$env:LOCALAPPDATA`）。

完整说明、运行数据与升级步骤见 [operations.md](../../docs/operations.md)。
