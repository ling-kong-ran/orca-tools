# VPS 上的 Orca：安装、配对与自启

配合[整套图文教程](claude-code-guide.md)使用。**Windows Orca 是客户端；VPS 也要安装 Orca，用无界面模式管理远程项目、账号、终端和 Claude 会话。**不是只装 Claude 或 SSH 就能使用全部远程功能。

当前 VPS 已部署 `orca-server.service`，最近核实的远程版本为 1.4.247。以下安装/创建服务步骤供新机器复现；已有服务不要覆盖，也不要并行启动第二个运行时。[官方安装](https://www.onorca.dev/docs/install) · [官方远程服务器说明](https://www.onorca.dev/docs/remote-servers)

## 1. 安装 Linux Orca

由管理员从 [stablyai/orca 官方 Releases](https://github.com/stablyai/orca/releases)下载兼容版本的 `.deb`，核对架构与发布包校验信息。当前 Ubuntu x64 使用 `amd64`，ARM 机器应选 `arm64`。

在 **root** 终端执行，先替换文件名：

```bash
apt install /tmp/orca-ide_实际版本_amd64.deb
```

`.deb` 的 CLI 通常位于 `/usr/bin/orca-ide`。由安装器配置依赖；若当前发行版缺依赖，先按报错处理，不要换成另一个同名 Orca 软件包。当前系统还有私有启动包装器，不能拿新机示例覆盖它。

运行 Orca/Claude 使用已有的普通用户，例如 `workspace`；Git、Claude Code、开发依赖和账号也应为这个用户准备。软件包安装使用 root，不代表日常开发使用 root。

## 2. 首次启动、配对、添加账号

先确认 Tailscale 连通，防火墙仅允许授权私网来源访问 6768。**普通用户**首次执行：

```bash
vps_ip='替换为VPS的Tailscale私网IPv4'
orca-ide serve --port 6768 --pairing-address "$vps_ip"
```

它在前台运行并输出配对链接。`--pairing-address` 不是监听地址限制，仍须阻止公网访问。

1. Windows Orca → **Settings → Remote Orca Servers → Add Server**。
2. 填写服务器名称，粘贴配对链接，添加并连接；看到 **Connected**。
3. 按本套环境的流程，先配置 **指纹浏览器 → VPS 代理出口 → Claude 官方网站**，核实实际出口，再完成官方注册/登录。保持这份独立浏览器配置和出口；Tailscale 连通不代表浏览器已经走 VPS 代理。详见[注册与登录步骤](deployment-center.md#注册与登录指纹浏览器使用-vps-出口)。
4. 保持服务器运行，在另一个同一普通用户的 VPS 终端执行：

```bash
orca-ide account add --agent claude
orca-ide account list
orca-ide repo add --path /home/workspace/Projects/mygame
```

项目路径换成实际已存在的仓库。完成登录后，Windows Orca 中选择这个远程服务器/项目，新建 Claude 会话；本机的账号登录态不会自动复制过去。

`account add` 给出的本次官方授权链接，应私下打开在上述指纹浏览器配置中。若默认浏览器被自动打开，先关闭该页面，再在指定配置中完成授权；按当前官方流程交还原来的 VPS 登录流程。代理口令、OAuth 链接与验证码不贴进 Agent 对话。

配对链接和账号列表属于私人信息，不公开截图。已经配对的客户端保存自己的授权，不需要每次重启都重新生成链接。

## 3. 配置 systemd 自启

**仅全新服务器使用下面的示例。**完成首次配对、尚未开始正式任务时，结束前台启动的 Orca，再由 root 创建 `/etc/systemd/system/orca-server.service`。将用户、UID、主目录、私网 IP 和 CLI 路径替换为实际值；UID 可用 `id -u workspace` 查询。

```ini
[Unit]
Description=Orca remote runtime
Wants=network-online.target
After=network-online.target tailscaled.service

[Service]
Type=simple
User=workspace
Group=workspace
WorkingDirectory=/home/workspace
Environment=HOME=/home/workspace
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PATH=/home/workspace/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/orca-ide serve --supervise --no-pairing --port 6768 --pairing-address 100.64.0.20
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
```

示例中的 `100.64.0.20` 是占位地址。`--no-pairing` 适用于已完成首次配对的常驻服务；`--supervise` 用于服务管理器。默认服务停止策略可能结束同组进程，不能把 `restart` 当作不影响 Claude 任务的常规操作。

root 执行：

```bash
loginctl enable-linger workspace
systemctl daemon-reload
systemctl enable --now orca-server.service
systemctl is-active orca-server.service
```

`enable-linger` 保持普通用户的 systemd 管理器在退出登录后运行。Orca 服务应显示 `active`；启用失败时先检查日志，不能再启动另一份抢占端口。

## 4. 验收与维护

| 检查 | 命令或操作 |
| --- | --- |
| 服务运行 | root：`systemctl status orca-server.service` |
| 启动日志 | root：`journalctl -u orca-server.service -n 50 --no-pager`；只反馈必要错误，不分享原始配对/令牌信息 |
| 私网端口 | Windows：`Test-NetConnection -ComputerName VPS私网IP -Port 6768` |
| 实际 RPC | Windows Orca 能列出远程仓库、终端；进一步在远程项目运行 Claude |
| 开机启动 | root：`systemctl is-enabled orca-server.service`；不必为验收中断当前任务重启 VPS |

当前环境另有 Tailscale 元数据隔离、OOM 优先级和访问限制，应沿用现有配置。连接超时先区分网络、服务和客户端状态，不要直接删配对信息或账号目录。

**数据通常位于普通用户的 `~/.config/orca`，自定义路径以当前服务配置为准。**其中有账号配置、会话和配对身份，升级要保留。维护前保存项目并确认任务状态；不要删除整个数据目录、批量杀 Claude 或承诺重启绝不丢任务。

需要更新时，从官方版本中选择兼容构建，按安装包说明安排停机维护；只替换程序不等于现有进程已加载新版本。新增配对必须使用当前版本支持的授权流程，不要因链接不可用而开放公网端口。
