# 部署中心：独立安装助手 + Agent 部署包

入口：新版 Orca Toolkit 统一管理页的 **部署中心**，或 Windows 独立安装包中的 `Start-OrcaDeploy.cmd`。两者共用计划、状态和执行代码，不依赖 Codex MCP。

当前版本是 **0.1.0 预览版 / Toolkit 1.4.1**。支持 Windows x64 客户端及 Ubuntu 22.04/24.04、Debian 12 x64 systemd VPS。

## 操作顺序

1. 新机器将独立包解压到具体非系统盘目录，双击 `Start-OrcaDeploy.cmd`；已有新版 Toolkit 用户直接打开“部署中心”。
2. 选“远程开发”或“远程开发 + GPU”，设置普通运行用户、目录和更新方式。
3. 两端 Tailscale 登录并连通。新 VPS 可先在厂商控制台按页面的最小引导步骤安装；已有设备不重复初始化。
4. 填写 VPS 私网地址及 SSH 用户，保存计划。获取并通过可信渠道核实主机指纹，再输入本次密码或复用现有认证。不会默认生成或上传 SSH 公钥。
5. 执行环境检查，阅读变更清单，批准当前计划，再安装缺失的依赖、Tailscale、Claude Code 与 VPS Orca。已有服务、账号、项目和活动任务保留。
6. 在“账号授权”先准备指纹浏览器：使用独立浏览器配置，通过已配置的 VPS 代理出口访问 Claude 官方网站，核实实际出口后再注册/登录；随后在同一浏览器配置中完成 VPS 发起的账号授权。验证码和条款由本人完成。普通运行用户与第三方账号不是同一个概念。
7. 首次前台 Orca 配对完成、结束该首次启动后，再设置服务自启。已有服务只复用，不自动重启。
8. 检查服务端结果，并在 Windows 侧验证实际 Orca 项目和终端请求。目标地址无法自动匹配时仍标为待确认。
9. GPU 方案再按 [GPU 教程](gpu-bridge.md) 配置软件、模型、每个 Claude 账号的 MCP 和项目镜像；执行一次小任务并取回产物后才算 GPU 验收完成。

Windows 准备可自动准备 Node 运行时和导入 Toolkit；缺少 Tailscale/Orca 时会交接官方安装流程。Orca 插件审核、第三方许可和设备审批仍需本人完成。安装助手不会假装这些操作已自动完成。

## 注册与登录：指纹浏览器使用 VPS 出口

本套环境的注册流程是：**指纹浏览器的独立配置 → 已配置的 VPS 代理出口 → [Claude 官方网站](https://claude.ai/)**。这里不是用浏览器打开 VPS 管理页注册，也不是把 Orca 的 6768 端口当作浏览器代理。

1. 先准备可用的 VPS 代理服务与连接配置。在指纹浏览器的独立配置中设置对应协议、代理地址、端口及必要认证；不要把代理密码写进 Agent 对话、教程或部署计划。
2. 在这份浏览器配置内检查实际公网出口是否为预期 VPS 出口，并检查是否有请求绕过代理。出口未确认或代理断开时，先停止注册/登录，修复连接后再继续。指纹浏览器名称、代理开关或 Tailscale 在线状态都不是出口验证结果。
3. 保持同一浏览器配置和 VPS 出口，直接打开 Claude 官方网站，由本人完成注册、登录、验证码及条款。代理和独立浏览器配置不替代服务的使用资格要求。
4. 在 VPS 的普通用户终端执行 `orca-ide account add --agent claude`。将本次官方授权链接私下打开在上述浏览器配置中；若自动打开了默认浏览器，先关闭那个页面，再使用指定配置完成本次授权。按当前官方流程把结果交还原来的 VPS 登录流程。
5. 用该 VPS 用户执行 `orca-ide account list`，再在对应账号启动一次 Claude 验证。浏览器注册成功、本机 Orca 已登录和 VPS 账号已授权分别确认。

当前助手只提供这一步的引导，不自动创建 VPS 代理服务、配置指纹浏览器或检测其出口。部署中心的 SSH 连接与指纹浏览器是两条连接：浏览器代理不会自动应用于安装助手，Tailscale 也不自动把浏览器访问 Claude 的流量改为 VPS 出口。

## 中断与重试

连接凭据不落盘，空闲连接 15 分钟后释放。任务计划与步骤结果保存在本机；窗口或助手重启后，先重新认证并检查实际状态，再继续同一个计划。

同一 VPS 的部署会加锁。未知结果、安装器超时或活动实例冲突时，不会自动启动第二份服务、重复登录或重建账号。

任务记录为 `needs-authorization`、`needs-attention` 或 `needs-inspection` 时，按当前步骤处理；只有运行到部分阶段不等于整套完成。

## Agent 部署包

保存计划后点“下载 Agent 部署包”。包含执行说明、计划、执行代码和现有验收记录；Windows 本机绝对路径和个人 Orca 环境标签不导出。SSH 密码、私钥、Cookie、OAuth 授权码和配对链接不包含在包内。

Agent 按包内 `DEPLOY.md` 执行。没有终端输入权限时，登录与提权要交回本人，不能在聊天中索要密码。配置和发行包的 ZIP 时间戳按 UTC 写入；接收产物仍使用 VPS 接收时间，不改写已有提交和资产。

## Git 加强隔离的边界

包内包含独立 Git 服务、固定 MCP 接口、Deploy Key 生成流程与整个 Claude 进程的隔离启动器。Deploy Key 默认单仓库只读；它不隐藏已有历史中的姓名、邮箱和时区。

加强组件必须先使用 **新测试仓库 + 新专用 Agent 用户** 验证。真实历史和凭据由独立服务账户保管，模型的源码工作区不含 `.git`。详见 [Git 服务部署与限制](../services/git-broker/README.md)。

当前已完成真实 Git 的状态、脱敏历史、diff、提交、push、快进 pull、越权拒绝及链接防护测试。**尚未完成 root 身份隔离和 Orca worktree / 会话恢复兼容性实机验收，不能标为正式环境已隔离，也不会迁移现有项目。**界面会持续显示相关待验收项。基础模式也不是 OS 文件访问边界，不能阻止有完整 shell/读取权限的 Agent 直接读自己的真实仓库。

## 打包与验证

在 Windows Python 3.14 上：

```powershell
node scripts/build-toolkit-ui.cjs
python -X utf8 -m unittest discover -s services/deploy -p 'test_*.py' -v
node --test plugins/toolkit/test-deploy.cjs plugins/toolkit/test-unified-ui.cjs
python scripts/build-deploy-package.py
```

独立包使用 Python 官方嵌入运行时，构建时检查 Python 可执行文件的 Windows 签名；SSH 依赖从官方 PyPI 获取，具体版本记录在包内清单。外层文件清单和 ZIP SHA-256 用于完整性检查。本地预览包尚无安装助手发布签名，不冒充已签名正式发行版。

完整部署原理和日常使用见 [Claude Code 图文教程](claude-code-guide.md) 与 [VPS Orca 教程](vps-orca.md)。
