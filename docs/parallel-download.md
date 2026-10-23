# Downloads 模块部署

Downloads 已合并到 **Orca Toolkit**，不再单独安装 Parallel Downloads 插件。模块支持多路分块、暂停/继续、重试和 SHA-256 校验，与项目 Git 同步各自独立。

## 1. 前提

- Orca Windows 已连接 Linux 服务器，并打开远程项目。
- Windows OpenSSH Client（ssh.exe、ssh-keygen.exe）可用。
- VPS 有 Python3/OpenSSH server；普通用户可写自己的 ~/.ssh/authorized_keys，SSH Ed25519 主机公钥可读。
- 两台电脑 Tailscale 已连接，SSH 只使用 VPS 的私网 IPv4。

## 2. 配置统一插件

按 [Toolkit 部署](toolkit.md) 安装 `plugins/toolkit`，打开管理页 → Module settings → Parallel downloads，填写 Orca environment、VPS Tailscale IPv4、SSH user 和端口，保存。

旧 `%LOCALAPPDATA%/OrcaParallelDownloads/settings.json` 若存在且配置有效，会在首次启动时自动读取；任务与断点继续使用原运行目录。新版设置保存在 `%LOCALAPPDATA%/OrcaTools/settings.json`。只有旧版个人硬编码配置时，需要在新管理页填一次。

## 3. 下载

点击 **Manage downloads**，或按 **Ctrl+Alt+D**，进入同一 Toolkit 的 `/downloads/` 页面。输入远程文件绝对路径；保存目录旁的 **Browse…** 按钮打开 Windows 文件夹选择框，也可手动填写路径。取消选择保持原目录；上次选择的目录或成功创建下载任务时使用的目录会保存在本机，下次自动恢复。然后选择并行数。先用4路，网络不稳时减到2路。多路不会突破链路带宽上限。

任务在关闭 Orca/禁用模块时暂停；重新打开后 Resume。最终文件生成前校验 SHA-256。源文件修改时拒绝续传，需新建任务。未完成任务或临时访问未清理时，不能切换到另一台下载服务器；先完成或取消并清理。

传输走 Tailscale + SSH，不是浏览器大文件下载；通常无需关闭代理，但 TUN 路由冲突需在代理软件中放行私网。

## 权限与运行数据

- 每任务生成临时 SSH key，authorized_keys 用 restrict + forced-command 限制为该文件的有界读取，没有任意 shell。
- SSH 主机公钥通过已有 Orca 通道取得并固定，保留严格校验。
- 本机任务、断点、私钥在 `%LOCALAPPDATA%/OrcaParallelDownloads`，不应提交 Git。
- 远程 reader 在 `~/setup-orca/parallel-download-reader.py`，任务在 `~/.local/share/orca-parallel-download/jobs`。
- 完成/取消后尝试清理公钥；断网导致清理失败时用 Clear access。勿删正常登录密钥。
- Toolkit HTTP API 校验回环 Host、会话 token 与 POST Origin；不用公网端口。

旧 18770 下载页由 Toolkit 的 18774/downloads/ 替代；旧插件停用后旧页面断开是正常迁移结果。

目录偏好位于 `%LOCALAPPDATA%/OrcaTools/downloads-preferences.json`，只在本机读取，不传给 VPS。原生选择框只通过固定的受认证本机接口调用；不开放任意 PowerShell 命令。
