# Orca Tools

用于 Orca 远程开发的个人工具集合：在远程服务器管理 Claude 账号，将文件下载到 Windows，以及让远程 Claude 调用 Windows 上的 ComfyUI、Godot 和 Blender。

项目是独立的社区工具，使用 Orca 的本地运行时接口；不是 Orca 官方插件库。部分接口依赖 Orca 版本，升级后应先运行检查。仓库只保存源码、示例配置和部署文档，不保存登录态、密钥、真实连接配置或项目素材。

## 工具目录

| 工具 | 用途 | 运行位置 | 部署说明 |
| --- | --- | --- | --- |
| [Account Switcher](tools/account-switcher/) | 切换远程 Orca 管理的 Claude 账号，显示额度与重置时间，遮罩邮箱 | Linux VPS；本机通过 Orca 远程浏览器打开 | [账号工具部署](docs/account-switcher.md) |
| [Parallel Downloads](plugins/parallel-download/) | 并行分块下载、暂停续传、重试、SHA-256 校验 | Windows Orca 插件 + 临时远程只读 SSH reader | [下载插件部署](docs/parallel-download.md) |
| [GPU Workflows](plugins/gpu-workflows/) | 从 Orca 打开本机 GPU 管理页，必要时启动桥接服务 | Windows Orca 插件 | [GPU 全套部署](docs/gpu-bridge.md) |
| [Local GPU Bridge](services/local-gpu-bridge/) | ComfyUI 工作流、Godot GPU 截图/GDScript、Blender 操作/Python、Git 渲染副本更新 | Windows 服务 + Linux Claude Code MCP 插件 | [GPU 全套部署](docs/gpu-bridge.md) |
| [Orca Startup](tools/orca-startup/) | 登录 Windows 后等待 Orca，自动激活已审核启用的插件 | Windows 后台助手 | [自启、升级与移除](docs/operations.md) |

## 先部署哪个

- 只需要切账号：按 [账号部署](docs/account-switcher.md) 操作，不需要 GPU 服务。
- 下载大文件经常停住：按 [下载部署](docs/parallel-download.md) 操作，不需要 GPU 服务。
- 让远程 Claude 用本机 GPU：按 [GPU 部署](docs/gpu-bridge.md) 顺序安装 Windows 服务、远程 MCP、Orca 入口插件。
- 希望登录后自动恢复：最后安装 [自启助手](docs/operations.md)。防火墙规则持久保存，不需要每次重启重新执行。

## 环境与兼容性

- Windows 10/11；Linux VPS（systemd 用户服务用于账号面板）。
- Orca 桌面及远程运行时已连接。GPU 入口要求 Orca `>=1.4.237`；下载插件 `>=1.4.229`。内部 RPC、安装器和 CLI 命令可能随版本变化。
- Windows Python **3.10+**、Node.js **18+**、Git；Linux Python **3.10+**，GPU MCP 另需已登录的 Claude Code。
- 本机与 VPS 已登录同一个获授权的 Tailscale 网络。服务绑定私网/回环，不开公网端口。
- GPU 功能还需本机 ComfyUI/Godot/Blender；工具不会自动下载模型、渲染器或运行不明安装包。
- 仓库整理版本：Local GPU Bridge **1.4.0**、GPU Workflows **1.0.1**、Parallel Downloads **1.0.3**。后两者加入可迁移配置，区别于原机器安装版。

## 数据与执行边界

GPU 通道使用 Tailscale 加密传输、Bearer token 与来源地址白名单；管理页只绑定 `127.0.0.1`。标准远程结果过滤硬件、网络身份、本机路径和原始日志。执行 GDScript/Python 的项目必须可信：它们仍具有本机用户权限；文本过滤不能保证抵御恶意代码编码或嵌入数据。参见 [隐私与架构](docs/architecture.md)。

开发只在 VPS，本机项目是渲染副本。项目同步**只使用 Git**：VPS commit/push → 本机渲染前 fetch/reset → GPU 渲染 → 取回结果。本机受跟踪改动先备份再丢弃，非冲突未跟踪产物保留。没有另一套上传同步入口，也不暴露通用 shell 工具。

## 本地验证

在仓库根目录运行（Windows PowerShell 示例）：

```powershell
python scripts/check.py
python scripts/test_install.py
python tools/account-switcher/test_panel.py
Push-Location services/local-gpu-bridge
python -m unittest test_bridge test_workflow_library test_native_control test_native_git -v
Pop-Location
node --test plugins/parallel-download/test.cjs plugins/parallel-download/test-settings.cjs
python plugins/parallel-download/test_remote.py
```

测试使用临时目录、临时 Git 仓库和模拟渲染器，不调用真实账号或公网模型服务。测试不代表目标电脑的显卡驱动、模型和防火墙已经就绪，首次部署仍需按文档执行验收。

## 维护

部署、升级、备份与卸载见 [运维说明](docs/operations.md)。不要提交 `*.local.json`、运行目录、OAuth 凭据、SSH 私钥、日志或渲染素材；`.gitignore` 与静态检查已覆盖常见情况，但不能代替人工审查。
