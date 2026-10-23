# GPU Workflows / Local GPU Bridge 部署

目标：开发在 Linux VPS，本机 Windows 提供 GPU。支持直接调用已保存的 ComfyUI 工作流、Godot 场景截图/项目 GDScript、Blender 操作与项目 Python。**不是把本机显卡变成 VPS 的 PCIe 设备**，而是远程提交任务、本机执行、取回结果。

以下命令中的服务器名、IP 和目录均为示例。按 Windows → VPS → Orca 入口的顺序部署。

## 1. Windows 准备

安装 Python 3.10+（需含 pythonw.exe）、Git、Tailscale，以及需要的 Godot/Blender/ComfyUI。登录 Tailscale，确认本机和 VPS 的私网地址。

本机渲染项目先用 Git 克隆一次，配置访问私有仓库所需的 SSH key/凭据，并确认不会弹交互登录：

```powershell
git clone <YOUR_GIT_REMOTE_URL> D:/Projects/game
git -C D:/Projects/game fetch origin
```

占位符命令中的 URL 需要替换，不能原样运行。此项目作为渲染副本，本机不做开发。`root` 必须是 Git 仓库根目录，Godot 子目录另填 `godot_subdir`，如 `client`。Godot 位于仓库根时可在仓库中使用专用子目录结构；当前管理器要求一个明确的相对 Godot 子目录，不能填 `.`。

## 2. 安装 Windows 服务

在仓库根目录执行：

```powershell
Copy-Item scripts/gpu-settings.example.json scripts/gpu-settings.local.json
notepad scripts/gpu-settings.local.json
python scripts/install-local-gpu.py --settings scripts/gpu-settings.local.json
```

修改配置：

| 字段 | 应填内容 |
| --- | --- |
| `listen` | 本机 Tailscale IPv4 |
| `allowed_peers` | 允许调用服务的 VPS Tailscale IPv4 列表 |
| `workflow_dirs` | 本机 ComfyUI 保存工作流的实际目录，支持多个 |
| `native.godot_executable` | 普通 Godot exe 的完整路径 |
| `native.blender_executable` | 普通 Blender exe 的完整路径 |
| `native.projects[].root` | 已克隆的本机渲染副本根目录 |
| `git.remote / git.branch` | 本机已有 remote 名称与远程分支，默认 origin/main |
| `allow_scripts` | 是否允许项目 GDScript / Blender Python；仅对可信项目开启 |

只用 ComfyUI 时，可以将 `native` 设为 `{"projects":[]}`；只用一种原生渲染器时删除另一种的 executable 字段。不需要 GPU 程序的安装包加入仓库。

安装器会：

1. 将程序复制到 `%LOCALAPPDATA%\LocalGpuBridge\app`，生成随机 token，保留已有 token。
2. 将 Godot/Blender 可执行文件复制为专用文件名，放在原安装目录旁；Blender 保持使用原目录的 DLL/资源，不影响正常 Blender。原安装目录需要当前用户可写，必要时先将完整软件目录安装/复制到用户可写位置。
3. 写入本机私有配置、启动器配置和 Windows 登录启动项；启动桥接服务。
4. 自动检查并申请安装专用渲染进程的持久防火墙规则；首次出现 Windows 管理员提示时需要本人确认。以后重启无须重复设置，缺失或失效才重新请求。
5. 导出 `%LOCALAPPDATA%\LocalGpuBridge\client.local.json`，供私下传给 VPS。

打开 `http://127.0.0.1:18773/`。确认已配置的渲染器显示 **Network privacy ready**，项目启用且有 **Auto-pull before rendering**。ComfyUI 需要另外启动，保持只监听本机回环地址，默认 8188。

> 如 Windows 防火墙阻止 VPS 入站访问 18772，可由管理员为**本机 Tailscale 地址 + 指定 VPS 私网源地址 + TCP 18772**创建窄范围允许规则；不要允许公网接口或任意来源。渲染器出站隔离规则与桥接入站规则是不同用途。Tailscale ACL 也必须允许这两个节点通信。

## 3. VPS 隔离 Tailscale 管理元数据

远程普通用户默认可能通过 Tailscale LocalAPI 看到对端公网端点。GPU 客户端会检查该前提，未隔离时拒绝工作。

由 VPS root/管理员执行一次，参数替换成实际运行 Orca/Claude 的普通用户：

```bash
sudo sh services/local-gpu-bridge/protect-tailnet-metadata.sh worker
```

脚本只适用于使用 `/run/tailscale` RuntimeDirectory 的 systemd tailscaled。它将目录改为 root 0700，并写入持久 drop-in，不重启网络。之后普通用户不能查询 tailscale status 等管理接口；私网传输仍正常，管理命令需 sudo。不适配此布局的系统会停止并要求管理员检查。

## 4. 私下传输连接配置

通过已信任的私网 SSH/SFTP 把 Windows 生成的 **client.local.json** 传到 VPS 用户的私人目录。例如：

```powershell
scp "$env:LOCALAPPDATA/LocalGpuBridge/client.local.json" worker@100.64.0.20:~/gpu-client.local.json
```

文件含 Bearer token；不要贴入聊天、截图、工单或提交 Git。IP 可私网可见，token 必须保密。没有任何真实 token 放在本仓库。

## 5. 安装 Claude Code MCP 插件

VPS 上克隆本仓库后，使用运行 Claude 的普通用户执行：

```bash
chmod 600 ~/gpu-client.local.json
python3 scripts/install-vps-gpu.py --client-config ~/gpu-client.local.json
```

安装器创建本地 marketplace，使用 Claude 官方 CLI 添加、安装、更新和启用 `local-gpu@local-gpu-tools`，不会修改 OAuth 登录信息。私有连接配置存放于操作系统用户的 `~/.config/local-gpu-bridge/client.json`，权限 0600；不依赖每个账号隔离的 HOME。

**多个 Orca Claude 账号**：每个实际配置目录都要安装一次，可在 Orca 账号配置中确认目录，再传入：

```bash
python3 scripts/install-vps-gpu.py --client-config ~/gpu-client.local.json \
  --claude-config-dir /home/worker/.config/orca/claude-profiles/PROFILE_ID/home
```

安装后删除 VPS 上临时中转的 `~/gpu-client.local.json`（最终0600配置仍保留）；新账号加入后同样安装。对正在运行的 Claude 执行一次 `/reload-plugins`，然后 `/mcp` 检查 `local-gpu`、`godot-local`、`blender-local` 连接。

## 6. Orca 入口插件

在 Windows Orca 设置 → Plugins 导入 `plugins/gpu-workflows`，审核并启用。也可尝试 `node plugins/gpu-workflows/Install.cjs`；内部安装器不兼容时使用 UI 导入。

命令面板 **GPU Workflows: Open Manager** 或 **Ctrl+Alt+G** 打开管理页。该插件读取本机生成的 `launcher.json`，后台桥接未运行时用对应 Python 启动。它不是远程 MCP 本体，必须先完成前面的服务安装。

## 7. 验收与使用

1. 工作流：让 VPS Claude “检查 gpu_status，列出 list_workflows，运行一个现有工作流，查询 job_status 并取回产物”。支持的 ComfyUI 编辑器保存格式自动发现，不需要逐个手工导入；不支持的自定义控件可在本机转换为 API 格式后用 `manage.py import` 导入。
2. Git：让 Claude 对 `project_id="game"` 调用 `project_git(operation="status")`，再 `project_git(operation="pull")`，查询 `native_job_status` 到成功。
3. Godot：对真实存在的 scene 调用 `capture_scene`，可传场景 `user_args`；`run_project_script` 执行已同步的 `.gd`。
4. Blender：调用 `blender_operation(operation="scene_info")`；专用实例首次操作启动。Python 用 `execute_code` / `run_script`，返回回执，不返回原始进程日志。
5. VPS 修改**必须 commit + push**。下一次渲染前自动 fetch/reset 到配置的分支。本机受跟踪修改先备份到 `native/git-backups/<project-id>/<job-id>` 再覆盖，通常保留未跟踪渲染产物。不运行 git clean。

没有开放通用 shell、任意 Git 参数、修改远端 URL、本机 commit/push。二进制项目素材需进入仓库或由预先配置的依赖流程准备；当前不会自动运行 Git LFS pull 或递归更新 submodule。

## 可选：项目图库的 Go 服务器

Godot/Blender 普通渲染不依赖 Go。针对本项目图库中的游戏服务器适配器，可在 Windows settings 的 native 下添加：

```json
{"go_root":"D:/Go", "go_executable":"D:/Go/bin/go.exe"}
```

安装器会创建 `go-local-gpu.exe` 和受管理的 server 路径。Go 编译关闭 cgo、联网模块下载与工具链自动切换，依赖必须已缓存。`native_script.py` 中的图库进程代理针对 `server/` 与 `./cmd/gameserver` 等约定，不是所有 Godot 项目都通用；其他布局需要增加专用适配器，不能直接开放任意子进程。

升级/移除、备份恢复见 [operations.md](operations.md)；安全边界见 [architecture.md](architecture.md)。
