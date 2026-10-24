# 自启、升级、备份与移除

## 自动启动

Windows GPU 安装器创建 `Local GPU Bridge.vbs` 登录启动项，使用安装时的 `pythonw.exe` 隐藏启动服务。它在 **Windows 用户登录后**运行，不是无人登录时的系统服务。Tailscale 应使用自动启动的 Windows 服务；配置 comfy_startup.enabled=true 后桥接自动拉起现有 ComfyUI；未配置时才需另行启动。Toolkit 激活和 GPU 入口也会触发同一受锁保护的启动器。

Orca 入口插件按命令激活。要在 Orca 打开后自动激活 Toolkit，审核启用插件后执行：

```powershell
node tools/orca-startup/install.cjs
node "$env:LOCALAPPDATA/OrcaLocalTools/bootstrap.cjs"
```

第二条立即运行助手，终端需保持；也可注销后重新登录，由安装器创建的 `Orca Local Tools.vbs` 隐藏运行。助手每 15 秒检查默认安装路径的 Orca，启动已审核且启用的工具，不自动弹出网页；插件被手工禁用、需要重新授权或出现未知更新时，等待用户在 Orca 插件页审核。

此助手调用 Orca 本地运行时 API，不自动批准新版本，不创建公网监听。默认路径为 `%LOCALAPPDATA%\Programs\orca`；使用自定义 Orca 安装目录需调整安装器、runtime.cjs 和 bootstrap.cjs 中的定位逻辑。未来 Orca 内部 API 改动可能需要适配。

防火墙规则是 Windows 持久规则，重启电脑后仍生效。服务启动检查**实际活动策略**，不会只凭标记文件显示 ready。首次安装/规则缺失需要管理员提示，正常重启不需要重复确认。

## 升级

### Windows GPU 服务

1. 先在管理页确认任务全部完成；保存专用 Blender 场景，并用 **Stop managed Blender** 停止它。不要关闭无关编辑器。
2. 保存 `%LOCALAPPDATA%\LocalGpuBridge\config.json` 和工作流目录的私有备份，勿提交仓库。
3. 确认并停止桥接自身进程；不要按 python.exe 名称批量杀进程：

```powershell
$bridgeRoot = Join-Path $env:LOCALAPPDATA 'LocalGpuBridge'
$bridgePid = (Get-Content (Join-Path $bridgeRoot 'process.json') -Raw | ConvertFrom-Json).pid
$bridgeProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $bridgePid"
if ($bridgeProcess -and $bridgeProcess.CommandLine -like '*LocalGpuBridge*app*bridge.py*') {
  Stop-Process -Id $bridgePid
}
```

4. 在仓库执行 `git pull`，检查部署说明是否有迁移事项；确认 `gpu-settings.local.json` 仍符合当前管理页配置，再运行安装器。安装器保留旧 token、备份旧 config，重建设置文件中的配置；**管理页改过的项目/目录需先同步到 settings 文件**，避免被旧设置覆盖。
5. 重新安装远程 MCP（对每个 Claude profile 执行），在旧会话运行 `/reload-plugins`。不能只更新本机入口插件而不更新 VPS 客户端。

本仓库的通用安装器生成 `launcher.json`。此前只按个人路径手工安装的版本，应执行此迁移后再升级到新的 Toolkit GPU 入口，否则旧服务虽然在线，离线自动拉起时可能找不到 Python 配置。

### Orca 插件

重新导入相应插件目录并按 Orca 提示审核。升级 Toolkit 前先暂停下载任务；任务断点保存在原 OrcaParallelDownloads 运行目录，统一设置保存在 `%LOCALAPPDATA%\OrcaTools\settings.json`。旧独立插件迁移见 [toolkit.md](toolkit.md)。

### 自启助手

安装器不会覆盖已登记助手。升级前查看 `%LOCALAPPDATA%\OrcaLocalTools\bootstrap.pid`，用 `Get-CimInstance Win32_Process` 核对其命令行确实指向该目录的 bootstrap.cjs，再停止该 PID。确认进程已退出后仅删除该 `bootstrap.pid`，重新运行 `node tools/orca-startup/install.cjs`。不要杀掉全部 node.exe。

### 账号面板

在 VPS 更新仓库后重新运行 `python3 tools/account-switcher/install.py`，然后：

```bash
systemctl --user restart claude-account-panel.service
```

重装不会修改 Orca 管理的账号登录态。

## 运行数据与备份

| 路径 | 内容 | 能否提交 Git |
| --- | --- | --- |
| `%LOCALAPPDATA%/LocalGpuBridge/config.json` | 本机路径、地址、token、项目授权 | 否 |
| 同目录 `client.local.json` / VPS `~/.config/local-gpu-bridge/client.json` | 远程连接 token | 否 |
| 同目录 `workflows/` | 本机批准的工作流，可能含提示词/资源路径 | 私下备份 |
| 同目录 `native/git-backups/` | 本机被覆盖前的内容、patch、原提交 | 私下备份 |
| 同目录 `native/artifacts/`、`native/runs/` | 任务产物、临时脚本和本机日志 | 否 |
| `%LOCALAPPDATA%/OrcaParallelDownloads` | 任务、断点、临时任务私钥 | 否 |
| `%LOCALAPPDATA%/OrcaLocalTools/startup.log` | 自启助手状态 | 否 |

Git 更新每次先备份，再将**受跟踪文件**重置为配置的远端分支。Git refs/local-gpu-backups/<job-id> 保存旧 HEAD；备份目录保存 files.zip、changes.patch、state.json。恢复时先停止任务，查看 state.json，再将所需文件恢复到**另一份临时目录**验证，避免恢复过程被自动更新覆盖。本机是一次性渲染副本，正式修改应回到 VPS 提交推送。

## 常见故障

- **不能切账号/显示本机账号**：面板要在拥有远程 Orca 运行时的用户下启动，网页通过远程浏览器或 SSH 转发访问。切换后新建会话。
- **下载插件启动错误**：先检查 settings.json、Windows OpenSSH、远程项目是否打开；不要复制别人机器的 IP 或 SSH 用户名。
- **桥接在线但工作流 unavailable**：确认 ComfyUI 已启动；配置本机 comfy_startup 后登录自动启动，首次加载节点需稍等。检查 comfy-startup.log / comfy-launcher.log，不要重复打开多个实例。
- **GPU MCP 不连接**：依次确认本机开机、Tailscale 连通、桥接启动、允许来源与 token、VPS LocalAPI 隔离；检查当前 Claude profile 是否安装了插件。
- **Native network isolation is not ready**：看本机管理页与 bridge.log，确认管理员安装成功且 Windows 防火墙全部 profile 已启用。不通过设置假 ready 绕过检查。
- **画面仍是旧版本**：VPS 是否 commit/push 到配置分支？本机 Git job 是否 succeeded？未推送代码不会同步；Git LFS/submodule 需额外准备。
- **Git 更新失败**：检查 Git 凭据是否能非交互工作、仓库根目录是否准确、文件占用。服务对短暂 Windows unlink 错误有限重试，持续占用需关闭相关进程后重试。
- **Blender connected:false**：通常表示专用实例尚未启动；首次操作会启动。不要因此修改普通 Blender 实例。
- **插件仍说不支持参数/Python**：旧 Claude 会话执行 `/reload-plugins`，检查当前 profile 已更新；若项目自己的 CLAUDE.md/记忆仍记着旧限制，按实际工具 schema 更新。

## 停用与移除

1. Orca 设置中禁用/移除 Orca Toolkit；移除 Windows Startup 目录的 `Local GPU Bridge.vbs`、`Orca Local Tools.vbs`，按上述方法核对并停止对应 PID。
2. 完成任务后备份运行数据，再自行移除 LocalGpuBridge/OrcaLocalTools 目录；下载未完成前不要删断点或密钥。
3. VPS `claude plugin uninstall local-gpu@local-gpu-tools --scope user`（各 profile 分别设置 CLAUDE_CONFIG_DIR），面板用 `systemctl --user disable --now claude-account-panel.service`。
4. 若不再使用渲染隔离，由管理员查看并只移除 `LocalGpuBridge-*` 规则。专用 exe 是安装器创建的副本，可在不运行时删除；不要删除原渲染器。
5. 保持 VPS Tailscale 元数据隔离不影响传输。若管理员确需恢复普通用户 LocalAPI 权限，移除对应 `50-local-api-private.conf`、daemon-reload 并恢复 `/run/tailscale` 原权限；这会恢复公网端点可见性，GPU 客户端会拒绝继续，直到重新隔离。

## 可选 CI

docs/ci-check.example.yml 提供 Windows GitHub Actions 测试流程模板。当前仓库提交不启用 workflow；如需启用，使用具有 workflow 权限的 GitHub 授权，将该文件放到 .github/workflows/check.yml 后提交。所有测试命令也可按 README 在本机运行。
