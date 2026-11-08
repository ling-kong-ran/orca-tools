# Orca Tools

用于 Orca 远程开发的个人工具集合：在远程服务器管理 Claude 账号，将文件下载到 Windows，以及让远程 Claude 调用 Windows 上的 ComfyUI、Godot、Blender、VRoid Studio 和 Tripo Studio。

项目是独立的社区工具，使用 Orca 的本地运行时接口；不是 Orca 官方插件库。部分接口依赖 Orca 版本，升级后应先运行检查。仓库只保存源码、示例配置和部署文档，不保存登录态、密钥、真实连接配置或项目素材。

**新手先看：[Claude Code 远程开发图文教程](docs/claude-code-guide.md)**，包含 Tailscale、VPS Orca 服务、工具集部署、日常使用、Git/GPU 流程和排错速查。

**新机器部署：[部署中心与独立安装助手](docs/deployment-center.md)**。Toolkit 1.4 系列新增统一部署入口，也可运行不依赖 Codex 的 Windows 独立包，或导出 Agent 部署包。当前为预览版；Git 加强隔离尚需系统权限与 Orca 会话兼容验收，不迁移现有项目。

## 新用户：clone 后如何开始

下面的命令在 **Windows 本机的 PowerShell** 中执行，不是在 VPS 上执行。源码启动需要 Git 和 Python **3.10+**；不需要预装 Codex、Orca 或 Node 才能打开部署向导。VPS 当前支持 **Ubuntu 22.04/24.04、Debian 12，x64、systemd**。

### 1. 下载源码，打开部署向导

先在准备存放源码的目录打开 PowerShell；希望放在非系统盘，就先进入那个盘上的目录。执行：

```powershell
git clone https://github.com/ling-kong-ran/orca-tools.git
cd orca-tools

python -m pip install -r services/deploy/requirements.txt
python services/deploy/deploy.py serve --open
```

最后一条命令会启动本机安装助手并打开网页。**使用期间保留这个 PowerShell 窗口**；浏览器没有自动打开时，复制终端输出的 `http://127.0.0.1:端口/` 地址打开。停止本机助手用 `Ctrl+C`，再次运行最后一条命令即可继续查看已保存的部署任务。

如果提示找不到 `git` 或 `python`，先安装对应软件并重新打开 PowerShell。有 `py` 命令的机器也可把两条 `python` 命令统一替换为 `py -3`。如果源码中没有 `services/deploy/deploy.py`，说明当前分支或版本尚未包含部署中心，应先核对版本。

### 2. 按网页顺序完成部署

1. **选方案**：只使用远程 Claude 选“远程开发”；需要本机截图、渲染等能力再选 GPU 方案。填写普通运行用户名和本机安装目录。
2. **准备私网**：两端安装、登录 Tailscale，确认连通。全新 VPS 没有 Tailscale/Python 时，展开网页“全新 VPS 尚未安装 Tailscale？”的引导，在厂商控制台完成前置安装与授权。
3. **连接 VPS**：填写 VPS 的 Tailscale 私网 IPv4、SSH 用户及端口，保存计划。通过厂商控制台等可信渠道核对 SSH 主机指纹，再输入本次认证信息；不要把密码发给 Agent。
4. **检查并安装**：先运行环境检查，阅读变更清单并确认，再安装缺失的依赖、普通运行用户、Claude Code 和 **VPS 上的 Orca**。已有服务、账号、项目和活动任务保留，不自动重启。
5. **完成 Windows 准备**：在“组件安装”中点“准备 Windows Tailscale / Orca / Toolkit”。缺少 Tailscale 或 Orca 时，按提示完成官方安装后重试；Toolkit 文件导入后，在 Orca 的 **Settings → Plugins** 刷新列表、审核并启用。
6. **注册与授权账号**：先准备“**指纹浏览器独立配置 → VPS 代理出口 → Claude 官方网站**”，本人核实实际出口后完成注册/登录。然后用同一浏览器配置完成 VPS 普通用户发起的 `account add` 授权；具体操作见[注册与登录步骤](docs/deployment-center.md#注册与登录指纹浏览器使用-vps-出口)。当前助手不自动部署代理或配置指纹浏览器；浏览器代理、Tailscale 与安装助手的 SSH 连接分别核实。
7. **配对并自启**：按“账号授权”生成的交接步骤，在 Windows Orca 添加 VPS。首次配对完成并结束首次前台启动后，再配置常驻服务；已有正式服务直接复用。
8. **验收**：运行服务器验收，并在 Windows 验证实际 Orca 项目/终端请求；在所选账号启动一次 Claude。GPU 方案还需按 [GPU 部署文档](docs/gpu-bridge.md) 完成配置，实测截图和产物回传。

官方账号注册、登录、验证码、条款、设备授权及插件审核由本人完成。**安装成功、浏览器登录成功、VPS 账号授权成功和远程连接成功需要分别确认。**详细步骤与失败后续跑见[部署中心教程](docs/deployment-center.md)。

### 3. 日常从哪里打开

Toolkit 启用后，按 **Ctrl+Alt+T** 打开统一管理页，进入 **部署中心**；Accounts、Downloads、Projects、Workflows 也在同一页面。已有 Toolkit 的用户直接使用这个入口，无需重复安装。

不想配置 Python 的用户，可以使用随版本提供的 **Orca Deploy Windows 独立安装包**：解压到具体目录后双击 `Start-OrcaDeploy.cmd`，进入相同向导，不需要 clone 或预装 Python。部署包格式和使用说明见[独立安装助手](docs/deployment-center.md)。

## 一个插件，三个业务模块

在 Orca 中只需安装 [Orca Toolkit](plugins/toolkit/)，用 **Ctrl+Alt+T** 打开统一管理页 `http://127.0.0.1:18774/`。

| 模块 | 职责 | 管理方式 | 部署说明 |
| --- | --- | --- | --- |
| Accounts | 切换远程 Claude 账号、查看用量与重置时间 | Toolkit 本机账号页，通过已有远程连接切换 | [账号部署](docs/account-switcher.md) |
| Downloads | 并行下载、暂停续传、重试、SHA-256 校验 | Toolkit 内的下载页面；Ctrl+Alt+D | [下载模块](docs/parallel-download.md) |
| GPU | ComfyUI、Godot、Blender、VRoid、Tripo Studio、Git 渲染副本 | Toolkit 查看在线状态并打开本机 GPU 管理页；Ctrl+Alt+G | [GPU 部署](docs/gpu-bridge.md) |

Toolkit 统一管理模块入口、连接配置、启用状态与启动。账号凭据留在 VPS，GPU 服务留在 Windows，Claude MCP 插件留在 VPS；它们不是额外需要安装的 Orca UI 插件。模块各自执行任务，单个模块未配置不影响其余模块。

首次安装和旧独立插件迁移先看 **[Toolkit 部署与迁移](docs/toolkit.md)**。不再同时启用旧 GPU Workflows / Parallel Downloads 插件。

## 后台组件

- [可选旧账号面板/CLI](tools/account-switcher/)：Linux 普通用户服务；新版 Toolkit 直接调用远程 RPC，无需部署该面板。
- [Local GPU Bridge](services/local-gpu-bridge/)：Windows GPU 执行服务与 Linux Claude MCP 插件。
- [VRoid Studio](docs/vroid.md)：角色预设、脸型体型、颜色、镜头、模型预览和项目保存。
- [Tripo Studio](docs/tripo.md)：用自己的 Studio 会员账号（国内站或国际站）图生/文生 3D、重拓扑、贴图、绑骨和动画；账号只留在本机。
- [Unity](docs/unity.md)：本机 Unity LTS 编辑器与官方 CLI/Pipeline 接入同一工具集，VPS 开发、本机运行与视口截图。
- [多语言配音](docs/tts.md)：Qwen3 TTS 的中英文及其他语言参数、音色与排错。
- [登录助手](tools/orca-startup/)：等待 Orca 打开，自动激活用户已审核启用的 Toolkit。
- [运维说明](docs/operations.md)：自启、备份、升级和移除。

## 环境与兼容性

- Windows 10/11；Linux VPS（systemd 用户服务用于账号面板）。
- Orca 桌面及远程运行时已连接。Toolkit 要求 Orca `>=1.4.237`。内部 RPC、安装器和 CLI 命令可能随版本变化。
- Windows Python **3.10+**、Node.js **18+**、Git；Linux Python **3.10+**，GPU MCP 另需已登录的 Claude Code。
- 本机与 VPS 已登录同一个获授权的 Tailscale 网络。服务绑定私网/回环，不开公网端口。
- GPU 功能还需本机 ComfyUI/Godot/Blender；工具不会自动下载模型、渲染器或运行不明安装包。
- 当前版本：Orca Toolkit **1.4.1**、Local GPU Bridge/MCP **1.9.2**。旧独立插件已合并为 Toolkit 内部模块。

## 数据与执行边界

GPU 通道使用 Tailscale 加密传输、Bearer token 与来源地址白名单；管理页只绑定 `127.0.0.1`。标准远程结果过滤硬件、网络身份、本机路径和原始日志。执行 GDScript/Python 的项目必须可信：它们仍具有本机用户权限；文本过滤不能保证抵御恶意代码编码或嵌入数据。参见 [隐私与架构](docs/architecture.md)。

开发只在 VPS，本机项目是渲染副本。项目同步**只使用 Git**：VPS commit/push → 本机渲染前 fetch/reset → GPU 渲染 → 取回结果。本机受跟踪改动直接丢弃，不创建项目同步备份，非冲突未跟踪产物保留。没有另一套上传同步入口，也不暴露通用 shell 工具。

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
