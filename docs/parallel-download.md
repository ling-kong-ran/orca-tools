# Parallel Downloads 部署

下载插件从 Linux VPS 分块读取文件到 Windows，支持多路、暂停/继续、失败重试与最终 SHA-256 校验。它是**下载工具**，不参与项目 Git 同步。

## 1. 前提

- Orca Windows 桌面已连接目标 Linux 服务器，并打开至少一个远程项目。
- Windows OpenSSH Client（`ssh.exe`、`ssh-keygen.exe`）可用。通常位于 `%WINDIR%\System32\OpenSSH`。
- VPS 有 Python 3、OpenSSH server，普通用户可写自己的 `~/.ssh/authorized_keys`，`/etc/ssh/ssh_host_ed25519_key.pub` 可读。
- 两台电脑 Tailscale 已连接；SSH 目标使用 VPS 的 **100.64.0.0/10 私网地址**。

## 2. 配置

先复制示例，修改三个字段：Orca 服务器名称、私网 IP、Linux SSH 用户名。不要将真实配置加入仓库。

```powershell
$downloadRoot = Join-Path $env:LOCALAPPDATA 'OrcaParallelDownloads'
New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
Copy-Item plugins/parallel-download/settings.example.json (Join-Path $downloadRoot 'settings.json')
notepad (Join-Path $downloadRoot 'settings.json')
```

示例的 `100.64.0.20` 不是真实服务器。`environment` 要与 Orca 内的名称一致；`sshUser` 要与远程运行时的用户一致，临时公钥会注册到该用户。

## 3. 导入插件

在 Orca 设置的 Plugins 页面导入目录 `plugins/parallel-download`，审核后启用。也提供了安装辅助命令：

```powershell
node plugins/parallel-download/Install.cjs
```

辅助命令依赖 Orca 当前内部安装器，仅用于默认安装路径；找不到安装器时改用设置页面导入目录。**不需要 `npm install`**。

用命令面板执行 **Parallel Downloads: Open Manager**，或按 **Ctrl+Alt+D**。管理页在本机 `http://127.0.0.1:18770/`。

## 4. 下载

输入远程文件的完整绝对路径，例如 `/home/worker/projects/video/dist/explainer.mp4`，选择本机目录与并行数，开始下载。先用 4 路，网络不稳定时减到 2 路；增加并行数不会突破链路带宽上限。

中途关闭后任务持久化为暂停状态，再打开页面继续。下载成功前使用临时文件，完成后校验 SHA-256，再生成最终文件。远程源文件在续传期间发生改变时会拒绝继续，需新建任务。

传输路径是 Windows → Tailscale → VPS SSH，不依赖浏览器大文件下载，也不经过公网 HTTP。一般无需关闭代理；代理/VPN 的 TUN 路由冲突仍可能影响 Tailscale，需在对应软件中放行私网路由。

## 权限与数据位置

- 每个任务生成临时 SSH 密钥，远程 authorized_keys 用 `restrict,command=...` 强制命令约束，只允许该文件的有界读取；没有任意远程 shell。
- 远程 SSH 主机公钥通过已连接的 Orca 通道取得并固定，SSH 保持严格主机校验。
- 本机运行数据、断点和任务私钥位于 `%LOCALAPPDATA%\OrcaParallelDownloads`，不能提交 Git 或上传给他人。
- 远程 reader 位于 `~/setup-orca/parallel-download-reader.py`；远程任务位于 `~/.local/share/orca-parallel-download/jobs`。
- 完成/取消任务会尝试清理临时公钥。断网造成清理失败时应在恢复后取消/清理对应任务；手工编辑 authorized_keys 前先备份，勿删除正常登录密钥。

插件错误停用时，先确认配置存在、OpenSSH 可运行、Orca 远程连接在线，然后在插件页查看错误。新版本需要重新审核时按 Orca 提示完成审核。
