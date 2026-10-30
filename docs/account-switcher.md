# Account Switcher 部署

这个工具读取 **运行它的 Linux 用户的 Orca 账号列表**，不是读取本机 Windows 的账号。账号必须先通过 Orca/Claude 正常登录。面板用 Orca RPC 切换账号，不复制或显示 OAuth token。

## 推荐：直接使用本机 Toolkit

1. 安装 Orca Toolkit 1.1.0+，确保 Orca 已连接目标远程环境。
2. 在 `http://127.0.0.1:18774/` 的 Module settings 中填写 Accounts 的 Orca environment，保存。
3. 点击 **Manage accounts**，本机进入 `/accounts/`，查看遮罩邮箱、用量和重置时间。
4. 点击 **Use this account**，等待 Selected；之后在远程项目中新建 Claude 会话。

此方式通过已有的 Orca 配对连接调用固定 accounts RPC，不需要远程 worktree、另开浏览器标签、额外 SSH 隧道或安装下面的旧面板。账号必须已在远程用户的 Orca 中登录；本机账号和远程账号是不同列表。首次加载显示已有用量缓存，Refresh usage 主动更新；缺失数据保持 Unknown。

Toolkit 1.2.2 起，点击账号卡片的 **Disable account** 可禁用该账号的切换按钮；后端也会拒绝选择该账号。点击 **Enable account** 恢复。状态按远程环境和账号 ID 保存至本机 `%LOCALAPPDATA%/OrcaTools/account-preferences.json`，刷新页面、保存设置或重启插件均保留。禁用不会删除登录或中断现有会话，也不会阻止通过其他 Orca 入口切换。

## 可选旧面板：在 VPS 安装

在拥有 Orca 远程运行时的普通用户终端中克隆本仓库，进入根目录；不要用 root 安装面板。

```bash
python3 tools/account-switcher/claude-account.py --list
python3 tools/account-switcher/install.py
systemctl --user status claude-account-panel.service
```

安装器将面板复制到 `~/.local/share/orca-tools/account-switcher`，将用户服务复制到 `~/.config/systemd/user` 并启用。服务只监听 VPS 的 `127.0.0.1:18766`。

如果第一条命令找不到运行时：先在 Orca 连接此服务器并打开远程项目。默认运行时元数据位于 `~/.config/orca/orca-runtime.json`。自定义数据目录可用 `ORCA_USER_DATA_PATH` 指定，并在 `systemctl --user edit claude-account-panel.service` 添加对应的 `Environment=`。

希望退出 SSH 后、服务器重启后也运行用户服务，可由管理员执行一次：

```bash
sudo loginctl enable-linger "$USER"
```

## 2. 从本机打开

以下仅适用于单独部署旧 VPS 面板。新版 Toolkit 的本机账号页见上文及 [统一插件部署](toolkit.md)。

旧面板可在 Orca 的该远程服务器浏览器中打开 `http://127.0.0.1:18766/`。这里的回环地址必须属于 VPS。

Windows 快捷脚本也可调用 Orca CLI 打开远程浏览器页：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/account-switcher/Open-Accounts.ps1 `
  -Environment 'My Remote Server' -Worktree 'path:/home/worker/projects/game'
```

`Environment` 填 Orca 内显示的服务器名称；`Worktree` 填已在远程 Orca 打开的项目绝对路径并带 `path:` 前缀。脚本假设 Orca 安装于默认 `%LOCALAPPDATA%\Programs\orca`。CLI 参数随版本改变时，可直接使用远程浏览器地址。

另一种方式是本机建立 SSH 端口转发；目标用 Tailscale 私网地址或已配置 SSH 别名：

```powershell
ssh -N -L 18766:127.0.0.1:18766 worker@100.64.0.20
```

保持该终端运行，然后用本机浏览器打开 `http://127.0.0.1:18766/`。示例 IP 需替换。不能将面板绑定到 `0.0.0.0` 或直接映射公网端口。

## 3. 切换与额度

1. 页面显示遮罩邮箱，选择目标账号。
2. 等待选中状态确认，再在 **VPS 项目中新建 Claude 会话**。
3. 已运行的 Claude 进程可能保留原账号登录态；切换不是迁移现有进程。
4. 额度/重置时间取自 Orca 返回的缓存，点击刷新更新。未取得数据时显示不可用，不把它当成零用量。

终端同样能切换：

```bash
python3 tools/account-switcher/claude-account.py
python3 tools/account-switcher/claude-account.py --select account@example.com
```

CLI 会在当前终端显示账号邮箱；网页默认遮罩邮箱。页面只返回用途所需状态；它不能替你订阅、支付或绕过平台登录验证。

## 故障与移除

```bash
journalctl --user -u claude-account-panel.service -n 50
systemctl --user restart claude-account-panel.service
# 停用
systemctl --user disable --now claude-account-panel.service
```

服务未启动通常是用户运行时/用户 DBus 未启动、Orca 未运行或 RPC 版本变化。不要分享 `orca-runtime.json`，其中含有运行时认证材料。
