"""Non-secret deployment plans. Never serialize connection credentials."""
import hashlib
import ipaddress
import json
import re

VERSION = 1
FIELDS = {'schema', 'profile', 'mode', 'connection', 'host', 'ssh_port', 'ssh_user',
          'runtime_user', 'install_dir', 'claude_version', 'orca_version',
          'orca_sha256', 'orca_asset_url', 'disable_claude_updates', 'build_tools',
          'environment', 'git_privacy', 'public_connection_approved', 'client_tailnet_ip'}


def validate(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError('部署计划包含未知字段；密码和密钥不得写入计划。')
    result = dict(schema=1, profile='base', mode='existing', connection='tailnet',
                  host='', ssh_port=22, ssh_user='root', runtime_user='workspace',
                  install_dir='', claude_version='stable', orca_version='',
                  orca_sha256='', orca_asset_url='', disable_claude_updates=False,
                  build_tools=False, environment='', git_privacy='basic',
                  public_connection_approved=False, client_tailnet_ip='')
    result.update(value)
    if result['schema'] != VERSION:
        raise ValueError('不支持的部署计划版本。')
    for name, allowed in [('profile', ('base', 'gpu')), ('mode', ('new', 'existing')),
                          ('connection', ('tailnet', 'ssh')), ('git_privacy', ('basic', 'isolated'))]:
        if result[name] not in allowed:
            raise ValueError('不支持的部署选项：' + name)
    for name in ('disable_claude_updates', 'build_tools', 'public_connection_approved'):
        if type(result[name]) is not bool:
            raise ValueError('开关必须是布尔值。')
    for name in ('host', 'ssh_user', 'runtime_user', 'install_dir', 'claude_version',
                 'orca_version', 'orca_sha256', 'orca_asset_url', 'environment', 'client_tailnet_ip'):
        text = result[name]
        if not isinstance(text, str) or len(text) > 2048 or re.search(r'[\x00-\x1f\x7f]', text):
            raise ValueError('部署配置文本无效。')
        result[name] = text.strip()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', result['runtime_user']) or result['runtime_user'] == 'root':
        raise ValueError('Claude 必须使用有效的专用普通用户名。')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', result['ssh_user']):
        raise ValueError('SSH 用户名无效。')
    if type(result['ssh_port']) is not int or not 1 <= result['ssh_port'] <= 65535:
        raise ValueError('SSH 端口无效。')
    if result['host']:
        try:
            address = ipaddress.ip_address(result['host'])
        except ValueError:
            raise ValueError('使用明确的 VPS IP，避免 DNS 重绑定和歧义。') from None
        normalized = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
        if normalized.is_loopback or normalized.is_unspecified or normalized.is_multicast or normalized.is_link_local:
            raise ValueError('不能将本机、链路本地或组播地址作为 VPS。')
        if result['connection'] == 'tailnet' and address not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('私网连接必须填写 VPS 的 Tailscale IPv4。')
        if result['connection'] == 'ssh' and not result['public_connection_approved']:
            raise ValueError('使用现有非 Tailscale SSH 前，需要明确确认连接路径。')
    if not re.fullmatch(r'stable|\d+\.\d+\.\d+', result['claude_version']):
        raise ValueError('Claude 版本必须为 stable 或明确版本号。')
    if result['orca_version'] and not re.fullmatch(r'v?\d+\.\d+\.\d+', result['orca_version']):
        raise ValueError('Orca 版本号无效。')
    if result['orca_sha256'] and not re.fullmatch('[a-fA-F0-9]{64}', result['orca_sha256']):
        raise ValueError('Orca SHA-256 无效。')
    if result['orca_asset_url'] and not re.fullmatch(
            r'https://github\.com/stablyai/orca/releases/download/v?\d+\.\d+\.\d+/[A-Za-z0-9_.+-]+\.deb', result['orca_asset_url']):
        raise ValueError('仅允许 Orca 官方仓库的明确版本 deb 包。')
    if result['client_tailnet_ip']:
        try:
            if ipaddress.ip_address(result['client_tailnet_ip']) not in ipaddress.ip_network('100.64.0.0/10'):
                raise ValueError()
        except ValueError:
            raise ValueError('本机来源必须是明确的 Tailscale IPv4。') from None
    return result


def digest(value):
    return hashlib.sha256(json.dumps(validate(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def agent_plan(value):
    # A VPS agent needs its server plan, not the Windows user's absolute path
    # or personal Orca connection label. Keep client-only settings on the PC.
    plan = validate(value)
    plan['install_dir'] = ''
    plan['environment'] = ''
    return plan


def agent_document(plan):
    plan = agent_plan(plan)
    return '''# Orca Deploy · Agent 执行说明

这是一份无秘密的部署计划。请使用随包的 deploy.py CLI 执行同一套检查和安装步骤。
不依赖 Codex MCP；需要普通终端、Python 3.10+，SSH 模式需要包内 Paramiko。

## 执行顺序
1. 阅读 DEPLOY.md；先建立 Tailscale 私网，使用 `probe` 获取主机指纹，由用户核实。
2. 使用 `inspect` 检查已有环境。密码只在终端 getpass 输入，不能写进聊天或计划。
3. 展示真实变更清单。执行 `apply` 时传入本次检查的计划摘要，并明确确认安装。
4. root/sudo 仅用于固定安装阶段；Claude、Orca 和账号使用普通用户运行。
5. 执行 `handoffs`。本人先准备指纹浏览器独立配置，经已配置的 VPS 代理出口直接访问 Claude 官方网站，核实实际出口后完成注册/登录；将 VPS `account add` 本次官方授权链接私下打开在同一浏览器配置中，完成原 VPS 登录流程。Tailscale、SSH 和浏览器代理分别核实，浏览器代理不会自动应用到安装助手。详见 docs/deployment-center.md 的注册与登录步骤。
6. 配对后再 `service` 配置自启；已有服务和运行任务必须保留。
7. `verify` 核查服务、账号状态和运行时；Windows 客户端还要验证实际 RPC。
8. GPU 方案按 docs/gpu-bridge.md 接入。没有完成截图与回传时，不能标为 GPU 验收通过。

## 边界
不要删除项目、账号、会话、配对数据；不要重写 Git 历史；不要自动清理磁盘。
不要为了排错放开公网、SSL 校验、任意 shell 或 Tailscale LocalAPI 权限。
不可把“端口通”当作“Orca 配对成功”，不可把 Deploy Key 当作 Git 元数据隔离。
加强 Git 模式先执行独立环境的权限和 Orca 兼容验收，不迁移正在使用的项目。
遇到官方注册、登录、MFA、条款、提权或必要重启，记录当前步骤并交接用户，随后续跑。
不要收集代理密码、浏览器配置或授权链接；没有本人核实，不宣称浏览器已经使用 VPS 出口。当前助手不自动部署 VPS 代理或配置指纹浏览器。
不可在普通日志、报告或 Agent 消息中输出邮箱、域名、凭据、授权 URL 和个人 SSH 配置。

## 本次配置（无密码、私钥、Cookie 或授权码）
```json
''' + json.dumps(plan, ensure_ascii=False, indent=2) + '\n```\n'
