# Orca Startup

Windows 登录助手，每 15 秒等待 Orca 并激活已审核启用的 GPU/下载插件，不弹出管理页，不自动批准新版本。

安装：`node install.cjs`。首次立即启动：`node "%LOCALAPPDATA%/OrcaLocalTools/bootstrap.cjs"`（CMD；PowerShell 使用 `$env:LOCALAPPDATA`）。

完整说明、运行数据与升级步骤见 [operations.md](../../docs/operations.md)。
