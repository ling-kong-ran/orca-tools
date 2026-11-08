# Orca Deploy

网页向导与 Agent 使用同一份计划和执行后端。当前仅支持 Windows 客户端及 Ubuntu 22.04/24.04、Debian 12 x64 systemd VPS。不会依赖 Codex MCP。

## 使用网页向导

已安装新版 Toolkit：统一管理页 → **部署中心**。首次加载需找到 Python，SSH 需要本包 `requirements.txt` 的依赖。

独立运行（源码）：

```powershell
python -m pip install -r services/deploy/requirements.txt
python services/deploy/deploy.py serve --open
```

新机器使用包含独立 Python 和 SSH 依赖的发行包，解压至所选非系统盘，双击 `Start-OrcaDeploy.cmd`（也可运行同名 `.ps1`）。运行时随包提供，无需先装 Orca、Node 或 Codex。不要把解压目录直接选为磁盘根目录。

1. 选择基础或 GPU 方案，填写运行用户名和安装目录。
2. 新 VPS 先通过厂商控制台安装并授权 Tailscale；已有设备复用私网。页面不擅自建立公网直连。
3. 保存计划、获取 SSH 主机指纹；通过厂商控制台独立核实后确认。
4. 提供本次密码，或复用已有 SSH 认证。不会默认创建或上传公钥。
5. 检查环境，阅读差异，批准当前摘要，再开始固定安装步骤。
6. 生成官方授权步骤。指纹浏览器使用独立配置，经已配置的 VPS 代理出口直接访问 Claude 官方网站；本人核实出口后注册/登录，并用同一配置完成 VPS `account add` 发起的授权。代理配置和浏览器出口需要本人准备与确认，助手不会自动代配。首次 Orca 配对完成、结束前台实例后再配置服务。已有服务不覆盖、不重启。
7. Windows 安装准备复用现有组件；缺少 Tailscale 或 Orca 时交接官方安装器，Toolkit 导入后需由用户审核。
8. 分别核查服务器、本机 RPC、GPU 与 Git 隔离。没有通过的项目会一直显示待完成。

## 给 Agent 使用

网页保存计划后可下载 Agent 部署包。包含无秘密的计划、同版本执行代码、验收记录和运行说明。CLI 示例：

```bash
python deploy.py create --plan deploy-plan.json
python deploy.py probe --id <任务ID>
# 用户在可信渠道核实指纹后；需要密码时在终端 getpass 输入
python deploy.py inspect --id <任务ID> --fingerprint SHA256:... --password-prompt
# 阅读检查输出后，采用当前输出中的 plan_hash
python deploy.py apply --id <任务ID> --fingerprint SHA256:... --password-prompt --approved-hash <plan_hash>
python deploy.py handoffs --id <任务ID> --fingerprint SHA256:... --password-prompt
python deploy.py service --id <任务ID> --fingerprint SHA256:... --password-prompt --approved-hash <plan_hash>
python deploy.py verify --id <任务ID> --fingerprint SHA256:... --password-prompt
```

CLI 与浏览器不会接受任意远端 shell 文本。第三方注册、订阅、验证码、条款、提权和必要重启需要本人完成。任务重启后先检查实际状态，不盲目重跑。账户“已注册”不等于 OAuth 一定未过期，正式使用前还需在所选账户启动一次 Claude 验证。

## Git 隐私

Deploy Key 只授予单仓库权限，不隐藏历史邮箱、姓名或时区。基础模式只约束接口输出，仍有 shell/文件权限的 Agent 可以读取 `.git`。

加强模式见 `git-broker/README.md`：可信服务与 Agent 使用不同用户，历史与密钥不在 Agent 可读目录中。先使用测试仓库执行权限检查；Orca worktree 等兼容性未验收前不能迁移正式项目。不会重写已有 Git 历史，也不承诺清洗源代码和文件内容中的全部身份信息。

## 状态与边界

任务记录默认在 Windows `%LOCALAPPDATA%/OrcaTools/deploy` 或 Linux `~/.local/state/orca-deploy`。密码只传入内存中的 SSH 认证，不写入计划、普通日志或导出包。主机指纹本身必须经可信渠道核实。

助手仅监听 127.0.0.1；校验 Host、会话令牌、Origin、JSON 类型及请求大小。安装器和网页不是通用 SSH 管理器，不自动放开公网端口、禁用 TLS、删除项目、清理磁盘或重建配对。

Python/Node 官方下载校验、上游包摘要和安装助手自己的文件完整性校验分别报告。没有独立签名验证时不会宣称完成独立来源认证。

GPU 按 `docs/gpu-bridge.md` 准备已有软件、模型和私有配置。当前安装助手调用现有安装脚本；检测到运行中的 Bridge 时会停止升级，不为安装结束编辑器或渲染任务。
