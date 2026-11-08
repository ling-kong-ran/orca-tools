"""Fixed Linux deployment stages. Executed over verified SSH, JSON in/out only.

No client-provided shell command is accepted. Raw installer output is never
returned to the browser or model. Existing Orca services and user data survive.
"""
import hashlib
import json
import os
import pathlib
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request


class StageError(Exception):
    pass


def find_tool(name):
    # Administrative binaries commonly live outside an ordinary user's PATH.
    # A restricted PATH must not be misreported as a missing installation.
    for prefix in ('/usr/bin', '/usr/sbin', '/bin', '/sbin', '/usr/local/bin', '/usr/local/sbin'):
        file = pathlib.Path(prefix) / name
        if file.is_file() and os.access(file, os.X_OK):
            return str(file)
    return None


def command(args, timeout=60, env=None, data=None, check=True):
    clean = {k: v for k, v in os.environ.items() if k in
             ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS')}
    clean.update(PATH='/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin', TZ='UTC',
                 GIT_TERMINAL_PROMPT='0', DEBIAN_FRONTEND='noninteractive')
    if env:
        clean.update(env)
    result = subprocess.run(args, input=data, capture_output=True, env=clean, timeout=timeout)
    if check and result.returncode:
        raise StageError('固定步骤执行失败：' + pathlib.Path(args[0]).name + '。请由管理员检查本步骤，避免把原始日志贴进聊天。')
    return result


def os_release():
    fields = {}
    for line in pathlib.Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            fields[k] = v.strip('"')
    return fields


def supported():
    info = os_release()
    return ((info.get('ID'), info.get('VERSION_ID')) in
            {('ubuntu', '22.04'), ('ubuntu', '24.04'), ('debian', '12')} and
            platform.machine() in ('x86_64', 'amd64') and pathlib.Path('/run/systemd/system').is_dir())


def user_info(plan):
    try:
        return pwd.getpwnam(plan['runtime_user'])
    except KeyError:
        return None


def as_user(plan, args, timeout=60, check=True, env=None):
    user = user_info(plan)
    if not user:
        raise StageError('普通运行用户尚未创建。')
    extra = {'HOME': user.pw_dir, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
             'PATH': user.pw_dir + '/.local/bin:/usr/local/bin:/usr/bin:/bin',
             'XDG_RUNTIME_DIR': '/run/user/' + str(user.pw_uid),
             'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/' + str(user.pw_uid) + '/bus'}
    extra.update(env or {})
    if os.geteuid() == user.pw_uid:
        return command(args, timeout=timeout, env=extra, check=check)
    if os.geteuid() != 0:
        raise StageError('此连接不能操作选定的普通用户；请使用授权的管理员连接。')
    return command(['runuser', '-u', user.pw_name, '--', 'env',
                    *[k + '=' + v for k, v in extra.items()], *args], timeout=timeout, check=check)


def require_root():
    if os.geteuid() != 0:
        raise StageError('此安装步骤需要 VPS 管理员权限；检查可以使用普通用户，不能把密码交给 Agent。')


def require_supported():
    if not supported():
        raise StageError('本版只执行经确认的 Ubuntu 22.04/24.04、Debian 12 x64 systemd 部署。')


def orca_path():
    for candidate in ('/usr/bin/orca-ide', '/opt/Orca/orca-ide'):
        if pathlib.Path(candidate).is_file():
            return candidate
    # Never choose the unrelated GNOME screen reader named "orca".
    return shutil.which('orca-ide')


def active_tasks():
    total = 0
    for proc in pathlib.Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            name = (proc / 'comm').read_text().strip().lower()
            if name.startswith(('claude', 'godot', 'blender', 'unity')):
                total += 1
        except OSError:
            pass
    return total


def services():
    names = []
    for name in ('orca-server.service', 'orca-ide.service', 'orca.service', 'orca-deploy-server.service'):
        result = command(['systemctl', 'show', name, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'UnitFileState'], check=False)
        fields = dict(line.split('=', 1) for line in result.stdout.decode(errors='replace').splitlines() if '=' in line)
        if fields.get('LoadState') == 'loaded':
            names.append({'name': name, 'active': fields.get('ActiveState') == 'active',
                          'enabled': fields.get('UnitFileState') == 'enabled'})
    return names


def tailnet():
    if not shutil.which('tailscale'):
        return {'installed': False, 'state': 'not-installed'}
    result = command(['tailscale', 'status', '--json'], timeout=15, check=False)
    if result.returncode:
        return {'installed': True, 'state': 'admin-check-required'}
    try:
        value = json.loads(result.stdout)
        ips = [x for x in (value.get('Self') or {}).get('TailscaleIPs', [])
               if re.fullmatch(r'100\.\d+\.\d+\.\d+', x)]
        return {'installed': True, 'state': value.get('BackendState', 'unknown'), 'private_ips': ips}
    except ValueError:
        return {'installed': True, 'state': 'unknown'}


def inspect(plan):
    info = os_release()
    user = user_info(plan)
    home = pathlib.Path(user.pw_dir) if user else None
    claude = home / '.local/bin/claude' if home else None
    available = {name: bool(find_tool(name)) for name in ('git', 'curl', 'python3', 'sshd', 'iptables', 'ip6tables')}
    available.update(claude=bool(claude and claude.is_file()), orca=bool(orca_path()), tailscale=bool(shutil.which('tailscale')))
    free = shutil.disk_usage('/').free
    changes = [{'component': name, 'action': 'reuse' if present else 'install'} for name, present in available.items()]
    memory = next((int(line.split()[1]) * 1024 for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')), 0)
    sudo_available = bool(find_tool('sudo')) and command(['sudo', '-n', 'true'], check=False).returncode == 0
    return {'supported': supported(), 'os': info.get('ID'), 'release': info.get('VERSION_ID'),
            'architecture': platform.machine(), 'free_bytes': free, 'enough_disk': free >= 3 * 1024 ** 3,
            'memory_bytes': memory, 'enough_memory': memory >= 3800 * 1024 ** 2,
            'admin': os.geteuid() == 0, 'sudo_available': sudo_available, 'runtime_user_exists': user is not None,
            'existing_orca_data': bool(home and (home / '.config/orca').exists()),
            'components': available, 'changes': changes, 'services': services(),
            'active_tasks': active_tasks(), 'tailscale': tailnet(),
            'needs_orca_package': not available['orca']}


def system(plan):
    require_supported()
    packages = ['ca-certificates', 'curl', 'git', 'python3', 'python3-venv', 'openssh-server', 'iptables']
    if plan.get('build_tools'):
        packages.append('build-essential')
    missing = [p for p in packages if command(['dpkg-query', '-W', '-f=${Status}', p], check=False).stdout.strip() != b'install ok installed']
    if missing or not user_info(plan):
        require_root()
    if missing:
        command(['apt-get', 'update'], timeout=600)
        command(['apt-get', 'install', '-y', '--no-install-recommends', *missing], timeout=900)
    created = False
    if not user_info(plan):
        command(['useradd', '--create-home', '--shell', '/bin/bash', plan['runtime_user']])
        created = True
    return {'packages_installed': missing, 'runtime_user_created': created, 'existing_data_preserved': True}


def download(url, destination, checksum=None, limit=500 * 1024 ** 2):
    request = urllib.request.Request(url, headers={'User-Agent': 'Orca-Deploy/1.0'})
    digest = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, 'xb') as out:
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > limit:
                raise StageError('官方安装包超过本步骤大小限制。')
            out.write(chunk)
            digest.update(chunk)
    if checksum and digest.hexdigest().lower() != checksum.lower():
        raise StageError('下载文件与锁定的 SHA-256 不一致，已停止。')
    return digest.hexdigest()


def tailscale(plan):
    require_supported()
    if shutil.which('tailscale'):
        return {'reused': True, 'status': tailnet()}
    require_root()
    info = os_release()
    family = info['ID']
    code = {('ubuntu', '22.04'): 'jammy', ('ubuntu', '24.04'): 'noble', ('debian', '12'): 'bookworm'}[(family, info['VERSION_ID'])]
    key = pathlib.Path('/usr/share/keyrings/tailscale-archive-keyring.gpg')
    source = pathlib.Path('/etc/apt/sources.list.d/tailscale.list')
    if key.exists() or source.exists():
        raise StageError('发现已有 Tailscale 软件源配置，请先检查，不自动覆盖。')
    with tempfile.TemporaryDirectory(prefix='orca-deploy-') as temp:
        pending = pathlib.Path(temp) / 'key.gpg'
        download(f'https://pkgs.tailscale.com/stable/{family}/{code}.noarmor.gpg', pending, limit=1024 * 1024)
        shutil.copyfile(pending, key)
        key.chmod(0o644)
    source.write_text(f'deb [signed-by={key}] https://pkgs.tailscale.com/stable/{family} {code} main\n')
    command(['apt-get', 'update'], timeout=600)
    command(['apt-get', 'install', '-y', 'tailscale'], timeout=600)
    command(['systemctl', 'enable', '--now', 'tailscaled'])
    return {'installed': True, 'needs_authorization': True, 'status': tailnet()}


def tools(plan):
    require_supported()
    user = user_info(plan)
    if not user:
        raise StageError('先创建普通运行用户。')
    orca_installed = False
    if not orca_path():
        require_root()
        url = plan.get('orca_asset_url', '')
        if not re.fullmatch(r'https://github\.com/stablyai/orca/releases/download/v?\d+\.\d+\.\d+/[A-Za-z0-9_.+-]+\.deb', url):
            raise StageError('环境检查尚未锁定 Orca 官方安装包。')
        with tempfile.TemporaryDirectory(prefix='orca-deploy-package-') as temp:
            package = pathlib.Path(temp) / 'orca.deb'
            checksum = download(url, package, plan.get('orca_sha256'))
            arch = command(['dpkg-deb', '-f', str(package), 'Architecture']).stdout.decode().strip()
            if arch != 'amd64':
                raise StageError('Orca 安装包架构不匹配。')
            command(['apt-get', 'install', '-y', str(package)], timeout=900)
        orca_installed = True
    claude = pathlib.Path(user.pw_dir) / '.local/bin/claude'
    claude_installed = False
    if not claude.is_file():
        target = plan.get('claude_version', 'stable')
        if not re.fullmatch(r'stable|\d+\.\d+\.\d+', target):
            raise StageError('Claude 版本无效。')
        # The downloaded script is executed only as the unprivileged runtime user.
        with tempfile.TemporaryDirectory(prefix='orca-deploy-claude-') as temp:
            folder = pathlib.Path(temp)
            script = folder / 'install.sh'
            download('https://claude.ai/install.sh', script, limit=4 * 1024 ** 2)
            if os.geteuid() == 0:
                os.chown(folder, user.pw_uid, user.pw_gid)
                os.chown(script, user.pw_uid, user.pw_gid)
            as_user(plan, ['bash', str(script), target], timeout=900)
        if not claude.is_file():
            raise StageError('Claude 安装器退出后未找到原生客户端。')
        claude_installed = True
    # Restrict a NEW runtime before the first foreground pairing, not only
    # when the user later installs its service. Existing instances stay intact.
    if not services():
        restrict_private_port(plan)
    return {'orca_installed': orca_installed, 'claude_installed': claude_installed,
            'account_login_required': True, 'package_sha256': checksum if orca_installed else None}


def restrict_private_port(plan, script_path=None):
    require_root()
    # Only 6768 is affected. Existing SSH, default policy and other services stay intact.
    firewall = pathlib.Path(script_path or '/usr/local/sbin/orca-deploy-private-port')
    content = '#!/bin/sh\nset -eu\n'
    import ipaddress
    try:
        peer = ipaddress.ip_address(plan.get('client_tailnet_ip', ''))
        if peer not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError()
    except ValueError:
        raise StageError('新建服务前需要明确的本机 Tailscale 来源地址，避免向整个 tailnet 放开。') from None
    for exe in ('iptables', 'ip6tables'):
        if not shutil.which(exe):
            raise StageError('缺少持久化私网端口限制所需工具。')
        import shlex
        rules = ([['-p', 'tcp', '--dport', '6768', '!', '-i', 'tailscale0', '-j', 'REJECT'],
                  ['-i', 'tailscale0', '!', '-s', str(peer), '-p', 'tcp', '--dport', '6768', '-j', 'REJECT']]
                 if exe == 'iptables' else [['-p', 'tcp', '--dport', '6768', '-j', 'REJECT']])
        for rule in rules:
            text = ' '.join(shlex.quote(x) for x in rule)
            content += f'{exe} -C INPUT {text} 2>/dev/null || {exe} -I INPUT 1 {text}\n'
    if firewall.exists() and firewall.read_text() != content:
        raise StageError('已有同名防火墙脚本，不自动覆盖。')
    firewall.write_text(content)
    firewall.chmod(0o755)
    command([str(firewall)])
    return firewall


def service(plan):
    require_supported()
    if not orca_path() or not user_info(plan):
        raise StageError('先完成 Orca 和普通用户安装。')
    existing = services()
    if existing:
        return {'reused_existing_service': True, 'services': existing,
                'changed': False, 'notice': '保留已有服务定义和运行进程，未重启。'}
    require_root()
    if active_tasks():
        raise StageError('检测到活动 Claude 或渲染任务。暂不交接服务，避免中断。')
    # Refuse to replace a running foreground runtime. Pairing must finish first.
    runtime = as_user(plan, [orca_path(), 'status', '--json'], timeout=20, check=False)
    if runtime.returncode == 0:
        raise StageError('前台 Orca 仍在运行。首次配对完成后先结束该前台启动，再配置服务；已有正式实例应保持。')
    private = tailnet()
    ips = private.get('private_ips') or []
    if private.get('state') != 'Running' or not ips:
        raise StageError('先完成 VPS Tailscale 登录，再启动 Orca。')
    help_text = as_user(plan, [orca_path(), 'serve', '--help'], timeout=20).stdout.decode(errors='replace')
    if '--supervise' not in help_text or '--no-pairing' not in help_text:
        raise StageError('当前 Orca CLI 不支持已验证的常驻参数，请使用对应版本官方服务安装方式。')
    firewall = restrict_private_port(plan)
    user = user_info(plan)
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', user.pw_dir):
        raise StageError('用户主目录需要单独审核，不能直接写入服务定义。')
    unit = pathlib.Path('/etc/systemd/system/orca-deploy-server.service')
    if unit.exists():
        raise StageError('发现已有部署服务，请先核查，不能重复创建。')
    environment = '\nEnvironment=DISABLE_AUTOUPDATER=1' if plan.get('disable_claude_updates') else ''
    unit.write_text(f'''[Unit]
Description=Orca remote runtime (Orca Deploy)
Wants=network-online.target
After=network-online.target tailscaled.service
[Service]
Type=simple
User={user.pw_name}
Group={user.pw_name}
WorkingDirectory={user.pw_dir}
Environment=HOME={user.pw_dir}
Environment=PATH={user.pw_dir}/.local/bin:/usr/local/bin:/usr/bin:/bin{environment}
ExecStartPre=+{firewall}
ExecStart={orca_path()} serve --supervise --no-pairing --port 6768 --pairing-address {ips[0]}
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
''')
    command(['systemctl', 'daemon-reload'])
    command(['systemctl', 'enable', '--now', unit.name])
    return {'service': unit.name, 'created': True, 'public_port_blocked': True, 'needs_runtime_check': True}


def handoffs(plan):
    cli = orca_path() or 'orca-ide'
    private = tailnet()
    ip = (private.get('private_ips') or ['<VPS私网IPv4>'])[0]
    return {'steps': [
        {'id': 'tailscale', 'title': '两端 Tailscale 官方授权',
         'command': 'sudo tailscale up', 'where': 'VPS 管理员终端',
         'instruction': '仅在尚未授权的新设备执行，打开命令给出的官方登录地址；已有设备不反复初始化。'},
        {'id': 'pair', 'title': '首次 Orca 配对', 'where': 'VPS 普通用户终端 + Windows Orca',
         'command': cli + ' serve --port 6768 --pairing-address ' + ip,
         'instruction': '安装阶段先限制 6768 只从本机私网来源访问。以 ' + plan['runtime_user'] + ' 普通用户执行，仅新环境且无已有实例时启动。将私密配对链接加入 Windows Orca；完成账号添加和配对后结束这份前台启动，再配置服务。'},
        {'id': 'browser-registration', 'title': '指纹浏览器：使用 VPS 代理出口注册 / 登录', 'where': '本机指纹浏览器的独立配置',
         'command': '',
         'instruction': '先准备已配置的 VPS 代理服务，在独立浏览器配置中设置其代理协议、地址、端口与必要认证。本人核实实际出口为预期 VPS 出口，且没有请求绕过代理后，再直接打开 Claude 官方网站完成注册/登录。保持同一配置和出口。当前助手不自动部署代理或配置浏览器；Tailscale 在线不代表浏览器已使用 VPS 出口。代理口令不写入部署计划或 Agent 对话。'},
        {'id': 'account', 'title': '授权 VPS 的 Claude 账号', 'where': '另一个 VPS 普通用户终端 + 上述指纹浏览器配置',
         'command': cli + ' account add --agent claude',
         'instruction': '在 Orca 运行时已启动的情况下，以 ' + plan['runtime_user'] + ' 执行。将本次官方授权链接私下打开在上述使用 VPS 出口的指纹浏览器配置中；若自动打开默认浏览器，先关闭该页面，再使用指定配置完成授权。按当前官方流程交还原 VPS 登录流程，再在该账号启动一次 Claude 验证。管理员可先切换到该用户；不要在 root 身份创建日常 Claude 账号。登录材料不粘贴到 Agent 对话。'},
        {'id': 'client', 'title': 'Windows 插件审核与连接验证', 'where': 'Windows Orca',
         'command': '', 'instruction': '审核启用 Toolkit，在部署中心验证所选远程环境的真实项目与终端请求。'},
    ]}


def verify(plan):
    value = inspect(plan)
    user = user_info(plan)
    runtime = False
    account_count = None
    if user and orca_path():
        result = as_user(plan, [orca_path(), 'repo', 'list', '--json'], timeout=25, check=False)
        try:
            decoded = json.loads(result.stdout)
            runtime = result.returncode == 0 and isinstance(decoded, dict) and decoded.get('ok', True) is not False
        except ValueError:
            pass
        accounts = as_user(plan, [orca_path(), 'account', 'list', '--json'], timeout=25, check=False)
        try:
            data = json.loads(accounts.stdout)
            collection = data.get('accounts', (data.get('data') or {}).get('accounts'))
            if isinstance(collection, list) and accounts.returncode == 0:
                account_count = len(collection)
        except (ValueError, AttributeError):
            pass
    configured = any(x['active'] and x['enabled'] for x in value['services'])
    deployed = command(['systemctl', 'is-active', 'orca-deploy-server.service'], check=False).stdout.strip() == b'active'
    enabled = command(['systemctl', 'is-enabled', 'orca-deploy-server.service'], check=False).stdout.strip() == b'enabled'
    checks = {'supported': value['supported'], 'runtime_user': value['runtime_user_exists'],
              'claude_installed': value['components']['claude'], 'orca_installed': value['components']['orca'],
              'tailscale_running': value['tailscale'].get('state') == 'Running',
              'service_autostart': configured or (deployed and enabled), 'server_rpc': runtime,
              'account_registered': account_count is not None and account_count > 0}
    return {'checks': checks, 'server_passed': all(checks.values()), 'account_count': account_count,
            'client_rpc_required': True, 'gpu_acceptance_required': plan.get('profile') == 'gpu',
            'git_isolation_verified': False}


def main():
    try:
        request = json.loads(sys.stdin.buffer.read(32768))
        operation = request['operation']
        plan = request['plan']
        if not isinstance(plan, dict) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', plan.get('runtime_user', '')) or plan['runtime_user'] == 'root':
            raise StageError('普通用户名无效。')
        operations = {'inspect': inspect, 'system': system, 'tailscale': tailscale,
                      'tools': tools, 'service': service, 'verify': verify, 'handoffs': handoffs}
        if operation not in operations:
            raise StageError('不允许的部署步骤。')
        result = operations[operation](plan)
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=True))
    except Exception as error:
        message = str(error) if isinstance(error, StageError) else '部署步骤未完成（' + type(error).__name__ + '）。请检查对应阶段，不要导出原始凭据日志。'
        print(json.dumps({'ok': False, 'error': message}, ensure_ascii=True))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
