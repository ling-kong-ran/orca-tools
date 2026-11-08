# Git 隐私服务：先测试，后考虑迁移

本组件只在 Linux 管理员控制的独立环境部署。它不是防封工具；Deploy Key 不隐藏 Git 历史。当前不自动替换正式项目的 `.git`，不改写已有提交，不把未通过的 Orca 兼容性检查标为成功。

## 权限结构

- `orca-git-broker` 系统用户保管 `/var/lib/orca-git-broker`，目录 0700，配置和密钥 0600。
- 新的专用普通 Agent 用户操作 `/srv/orca-agent-workspaces/<project>` 中的源码，目录内没有 `.git`。
- `/run/orca-git-broker/broker.sock` 只接受许可 UID；目录不可由 Agent 写入，接口仅包含固定的状态、差异、摘要历史、提交、fetch、快进 pull、push。
- 提交与写操作要求先获得当前 `head`，服务端核对后执行；不接受任意参数，不执行 hooks、external diff、textconv 或 shell。
- Git 远程身份、凭据和原始错误不返回给 Agent。源代码正文中本来就包含的信息仍需用户自行判断，不能承诺全量匿名。
- `isolated-launcher.py` 使用 bubblewrap 限制整个 Claude 进程、文件工具、shell、子进程和 MCP 的文件视图，提供独立 PID 命名空间，避免只靠 alias 或提示词约束。

## 在新的测试仓库验证

由管理员先阅读代码并安装系统的 `git`、`openssh-client`、`bubblewrap`。以下不应在 Agent 对话中传入真实凭据：

```bash
sudo python3 install.py prepare
# 在管理员终端编辑请求，权限 root:root 0600
sudo python3 install.py add-project --request-file /root/git-project-request.json
```

请求模板（不要把私钥、个人密码或 PAT 放进文件）：

```json
{
  "project_id": "sandbox-game",
  "agent_user": "orca-agent",
  "remote": "git@github.com:OWNER/TEST-REPO.git",
  "branch": "main",
  "allow_write": false,
  "create_deploy_key": true,
  "known_hosts": "/root/verified-github-known-hosts",
  "author_name": "Developer",
  "author_email": "YOUR-VERIFIED-NOREPLY-ADDRESS"
}
```

Git 主机公钥必须由管理员通过可信官方来源核实，不能用未经核实的 ssh-keyscan 结果直接信任。私钥在 broker 用户的私有目录生成；只有公钥展示给管理员，手动添加到这个测试仓库的 Deploy Keys。只读是默认值；确实需要提交推送时才单独设置写权限。仓库已有公开内容可使用 HTTPS 且不创建密钥；私有仓库需要准备隔离认证，不复制个人的全局 GitHub 凭据。

授权完成后：

```bash
sudo python3 install.py initialize --project sandbox-game
sudo python3 install.py install-service
sudo python3 install.py verify --project sandbox-game
sudo python3 isolated-launcher.py --project sandbox-game --self-test
```

前两项权限检查应显示私有 Git 数据不可读、源码目录无 `.git`。运行时自检还应验证宿主其他 HOME 和进程不可见。不要因为 broker 进程存在就宣告隔离成立。

然后以新的专用 Agent 用户安装/登录 Claude，并将 MCP 注册到这个用户的选定 Claude 配置目录：

```json
{
  "mcpServers": {
    "private-git": {
      "command": "python3",
      "args": ["/usr/local/lib/orca-git-broker/client.py", "--project", "sandbox-game"]
    }
  }
}
```

使用 `isolated-launcher.py` 从可信管理员运行时启动该专用 Claude。不要把脚本做成 Agent 可编辑的 setuid 包装器，不授予通用 sudo 或 Docker socket 权限。直接在普通宿主 shell 启动同用户 Claude 不等同于这个进程隔离边界。

## 必须单独确认的兼容性

该源码工作区没有 `.git`，普通 `git log`、`git commit` 等通过 MCP 替代。Orca 原生 worktree 创建、Git 状态、会话恢复、工具路径与插件加载必须在这份测试工作区逐项验证；目前自动检查会明确返回 `orca_worktree_compatible: false` 和 `ready_for_production: false`，不能直接迁移现有 Orca 项目。

不支持符号链接、submodules、LFS 指针和单文件超过 32 MiB / 工作区超过 256 MiB 的资产；发现时停止而不是静默漏文件。大资产需要独立、经授权的准备流程。提交与快进拉取失败后先查状态，不重复推送或强制重置。

此版本不自动安装全局 sudoers、重挂载宿主 `/proc`、关闭其他服务或修改现有账号。部署新服务的动作由管理员在独立测试环境确认执行。
