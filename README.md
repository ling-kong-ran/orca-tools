# Orca Tools

用于 Orca 远程开发的个人工具集合：在远程服务器管理 Claude 账号，将文件下载到 Windows，以及让远程 Claude 调用 Windows 上的 ComfyUI、Godot、Blender 和 VRoid Studio。

项目是独立的社区工具，使用 Orca 的本地运行时接口；不是 Orca 官方插件库。部分接口依赖 Orca 版本，升级后应先运行检查。仓库只保存源码、示例配置和部署文档，不保存登录态、密钥、真实连接配置或项目素材。

## 一个插件，三个业务模块

在 Orca 中只需安装 [Orca Toolkit](plugins/toolkit/)，用 **Ctrl+Alt+T** 打开统一管理页 `http://127.0.0.1:18774/`。

| 模块 | 职责 | 管理方式 | 部署说明 |
| --- | --- | --- | --- |
| Accounts | 切换远程 Claude 账号、查看用量与重置时间 | Toolkit 本机账号页，通过已有远程连接切换 | [账号部署](docs/account-switcher.md) |
| Downloads | 并行下载、暂停续传、重试、SHA-256 校验 | Toolkit 内的下载页面；Ctrl+Alt+D | [下载模块](docs/parallel-download.md) |
| GPU | ComfyUI、Godot、Blender、VRoid、Git 渲染副本 | Toolkit 查看在线状态并打开本机 GPU 管理页；Ctrl+Alt+G | [GPU 部署](docs/gpu-bridge.md) |

Toolkit 统一管理模块入口、连接配置、启用状态与启动。账号凭据留在 VPS，GPU 服务留在 Windows，Claude MCP 插件留在 VPS；它们不是额外需要安装的 Orca UI 插件。模块各自执行任务，单个模块未配置不影响其余模块。

首次安装和旧独立插件迁移先看 **[Toolkit 部署与迁移](docs/toolkit.md)**。不再同时启用旧 GPU Workflows / Parallel Downloads 插件。

## 后台组件

- [可选旧账号面板/CLI](tools/account-switcher/)：Linux 普通用户服务；新版 Toolkit 直接调用远程 RPC，无需部署该面板。
- [Local GPU Bridge](services/local-gpu-bridge/)：Windows GPU 执行服务与 Linux Claude MCP 插件。
- [VRoid Studio](docs/vroid.md)：角色预设、脸型体型、颜色、镜头、模型预览和项目保存。
- [多语言配音](docs/tts.md)：Qwen3 TTS 的中英文及其他语言参数、音色与排错。
- [登录助手](tools/orca-startup/)：等待 Orca 打开，自动激活用户已审核启用的 Toolkit。
- [运维说明](docs/operations.md)：自启、备份、升级和移除。

## 环境与兼容性

- Windows 10/11；Linux VPS（systemd 用户服务用于账号面板）。
- Orca 桌面及远程运行时已连接。Toolkit 要求 Orca `>=1.4.237`。内部 RPC、安装器和 CLI 命令可能随版本变化。
- Windows Python **3.10+**、Node.js **18+**、Git；Linux Python **3.10+**，GPU MCP 另需已登录的 Claude Code。
- 本机与 VPS 已登录同一个获授权的 Tailscale 网络。服务绑定私网/回环，不开公网端口。
- GPU 功能还需本机 ComfyUI/Godot/Blender；工具不会自动下载模型、渲染器或运行不明安装包。
- 当前版本：Orca Toolkit **1.1.2**、Local GPU Bridge/MCP **1.6.2**。旧独立插件已合并为 Toolkit 内部模块。

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
python -m unittest discover -p 'test_*.py' -v
Pop-Location
node --test plugins/toolkit/test.cjs plugins/toolkit/test-accounts.cjs plugins/toolkit/test-directory-picker.cjs plugins/toolkit/test-remote-browser.cjs plugins/toolkit/modules/downloads/test.cjs plugins/toolkit/modules/downloads/test-settings.cjs
python plugins/toolkit/modules/downloads/test_remote.py
```

测试使用临时目录、临时 Git 仓库和模拟渲染器，不调用真实账号或公网模型服务。测试不代表目标电脑的显卡驱动、模型和防火墙已经就绪，首次部署仍需按文档执行验收。

## 维护

部署、升级、备份与卸载见 [运维说明](docs/operations.md)。不要提交 `*.local.json`、运行目录、OAuth 凭据、SSH 私钥、日志或渲染素材；`.gitignore` 与静态检查已覆盖常见情况，但不能代替人工审查。
