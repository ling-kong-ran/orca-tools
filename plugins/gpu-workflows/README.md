# GPU Workflows 1.0.1

Orca Windows 入口插件：**Ctrl+Alt+G** 或命令面板 **GPU Workflows: Open Manager**。

先按 [GPU 部署说明](../../docs/gpu-bridge.md) 安装桥接服务，再导入本目录并审核启用。插件从 `%LOCALAPPDATA%/LocalGpuBridge/launcher.json` 读取本机 Python 路径，桥接服务离线时自动启动。没有 npm 依赖。

`Install.cjs` 依赖 Orca 内部安装器，失配时使用设置中的目录导入。自动激活见 [自启说明](../../docs/operations.md)。
