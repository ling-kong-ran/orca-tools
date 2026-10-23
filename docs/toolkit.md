# Orca Toolkit：安装与迁移

Orca 里只保留一个 **Orca Toolkit** 插件；业务拆为 Accounts、Downloads、GPU 三个内部模块。

## 新安装

1. Windows 安装 Node18+，打开已连接远程主机的 Orca（>=1.4.237）。
2. Orca 设置 → Plugins → 导入本仓库 `plugins/toolkit` 目录，审核并启用。也可运行 `node plugins/toolkit/Install.cjs`；辅助安装器依赖 Orca 内部结构，失败时用 UI 导入。
3. 用 **Toolkit: Open Manager** 或 **Ctrl+Alt+T** 打开 `http://127.0.0.1:18774/`。
4. Module settings 中填 Accounts/Downloads 各自的远程 environment；Downloads 再填私网IP、SSH用户/端口。Accounts 通过已有配对的 Orca 连接访问远程账号，无需 worktree。
5. 按模块需要安装 [GPU后台服务/MCP](gpu-bridge.md)。Accounts 无需另装 VPS 面板。没有安装的模块显示 Needs setup/Offline，不影响其他模块。
6. 安装 [Windows登录助手](operations.md)，即可在 Orca 打开后自动激活已审核启用的 Toolkit。

## 统一管理界面

- **Accounts**：Manage accounts 在本机打开同一服务的 `/accounts/` 页面，直接列出远程账号，保留邮箱遮罩、用量、重置倒计时和账号切换。Configured 只代表已填连接；页面实际请求远程 RPC 后才显示账号。只返回必要状态，OAuth 凭据留在远程。切换后新建远程 Claude 会话，已有会话不变。
- **Downloads**：同一18774服务的 `/downloads/` 页面。Browse remote 可进入服务器目录、返回上级/主目录、筛选和显示隐藏文件，再选择文件；也可手动填写绝对路径。按远程 environment 记住上次浏览目录和文件地址。保存目录使用 Windows 文件夹选择并独立记忆，支持暂停/续传/校验。
- **GPU**：显示本机服务实际在线状态，打开原18773管理页；服务未启动时尝试按 launcher.json 拉起。渲染、工作流、Git设置仍由GPU服务管理。
- **Module settings**：模块配置与启用状态。Accounts/GPU开关只控制 Toolkit 入口，不停止后台独立服务或远程正在执行的任务。Downloads关闭时暂停下载，开启后需手动恢复。

Accounts 和 Downloads 在同一本机 Toolkit 服务内管理；GPU 继续使用现有本机后台服务。账号操作与远程目录浏览只调用已有配对 Orca 连接中的固定 RPC，不增加远程端口或通用 shell。

## 从两个独立插件迁移

1. 旧下载页先 Pause all，确认任务停止；无需删除任务或密钥。
2. 在 Orca 停用 **Parallel Downloads**、**GPU Workflows**。保留后台 Local GPU Bridge；旧 VPS 账号面板可选保留，新版 Toolkit 不依赖它。
3. 导入启用 **Orca Toolkit**。首次启动若存在有效旧 `OrcaParallelDownloads/settings.json`，自动迁移连接参数；否则在管理页填一次。
4. 任务、断点和临时 SSH key 继续使用 `%LOCALAPPDATA%/OrcaParallelDownloads`。旧18770页面改用新18774/downloads/页面。
5. 保持 `%LOCALAPPDATA%/LocalGpuBridge` 原有配置/工作流/任务；GPU服务无需重装。若缺少 launcher.json，按GPU安装文档迁移安装器或由管理员写入实际 pythonw 路径，使离线启动可用。
6. 更新登录助手（先按运维文档核对并停止旧 bootstrap PID），新助手只激活 `local-tools.toolkit`，不会再重开旧两个插件。
7. 核对 Toolkit、下载与GPU页面可用后，可在Orca移除旧插件。不要同时启用旧插件和Toolkit下载模块，它们会争用相同任务目录。

VPS Claude MCP 与本次 Orca UI 合并相互独立；工具协议没变化，不需要因为UI合并而重新登录Claude。

## 配置与地址

| 内容 | 位置 |
| --- | --- |
| 统一管理页 | http://127.0.0.1:18774/ |
| 内置账号页 | http://127.0.0.1:18774/accounts/ |
| 内置下载页 | http://127.0.0.1:18774/downloads/ |
| Toolkit配置 | %LOCALAPPDATA%/OrcaTools/settings.json |
| 下载记录/断点 | %LOCALAPPDATA%/OrcaParallelDownloads |
| GPU管理页 | http://127.0.0.1:18773/ |
| 可选旧 VPS 账号面板 | 远程127.0.0.1:18766（Toolkit 不依赖） |

Toolkit设置不保存token、SSH私钥或OAuth。浏览器管理API仅回环监听，校验Host、Origin、会话token；没有任意shell或任意URL执行接口。部署自启后仍尊重Orca审核和手工禁用状态。

## 更新到 1.1.0

重新导入 `plugins/toolkit` 或运行安装器，然后在 Orca 插件页刷新，审核并启用新版。仍显示 Open accounts 的页面属于旧版，更新后刷新管理页，入口改为 Manage accounts。安装器不会重启 Orca；在方便时加载新版以免影响当前任务。旧 accounts.worktree 配置保留兼容，但不再参与账号打开。
