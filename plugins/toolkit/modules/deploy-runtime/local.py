"""Fixed Windows actions shared by standalone and Toolkit deployment surfaces."""
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import uuid
from engine import atomic_json


def source_root():
    here = pathlib.Path(__file__).resolve()
    for directory in here.parents:
        if (directory / 'scripts/install-local-gpu.py').is_file() and (directory / 'plugins/toolkit').is_dir():
            return directory
    # The installed Toolkit contains the small runtime, while the standalone
    # package retains the complete client installer. Reuse its local pointer.
    try:
        local = pathlib.Path(os.environ['LOCALAPPDATA']) / 'OrcaDeploy/launcher.json'
        directory = pathlib.Path(json.loads(local.read_text(encoding='utf-8-sig'))['source'])
        if directory.is_absolute() and (directory / 'scripts/install-deploy-client.ps1').is_file() and (directory / 'plugins/toolkit').is_dir():
            return directory
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def clean_env():
    names = ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'HOME',
             'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'ProgramFiles', 'ProgramFiles(x86)')
    return {key: value for key, value in os.environ.items() if key in names}


def orca_cli():
    local = pathlib.Path(os.environ.get('LOCALAPPDATA', pathlib.Path.home() / 'AppData/Local'))
    candidate = local / 'Programs/orca/resources/bin/orca.exe'
    if not candidate.is_file():
        raise ValueError('未找到 Windows Orca CLI。先完成桌面程序安装并启用 CLI。')
    return candidate


class LocalActions:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.busy = False
        self.lock = threading.Lock()

    def call(self, action, body):
        if os.name != 'nt':
            raise ValueError('此操作只在 Windows 安装助手上执行。')
        definitions = {'choose-folder': {'initialDirectory'}, 'verify-client': {'environment', 'expected_host'},
                       'install': {'install_dir', 'approved'}, 'gpu-install': {'settings', 'approved'}}
        if action not in definitions or set(body) - definitions[action]:
            raise ValueError('不允许的本机部署操作。')
        if action == 'choose-folder':
            return self.choose_folder(body.get('initialDirectory', ''))
        if action == 'verify-client':
            return self.verify_client(body)
        if body.get('approved') is not True:
            raise ValueError('先确认本机安装操作。')
        if action == 'gpu-install':
            return self.gpu_install(body)
        return self.install(body)

    def choose_folder(self, initial):
        if not isinstance(initial, str) or len(initial) > 4096:
            raise ValueError('目录输入无效。')
        script = pathlib.Path(__file__).with_name('choose-directory.ps1')
        if not script.is_file():
            root = source_root()
            script = root / 'plugins/toolkit/choose-directory.ps1' if root else script
        if not script.is_file():
            raise ValueError('目录选择器未包含在当前安装包中。')
        env = clean_env()
        env['ORCA_TOOLKIT_FOLDER_BASE64'] = base64.b64encode(initial.encode()).decode()
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(script)], capture_output=True, timeout=300, env=env,
                                creationflags=0x08000000)
        if result.returncode:
            raise ValueError('目录选择未完成。')
        return json.loads(result.stdout.decode('utf-8-sig'))

    def verify_client(self, body):
        environment = body.get('environment', '')
        expected = body.get('expected_host', '')
        if not isinstance(environment, str) or not environment.strip() or len(environment) > 200 or re.search(r'[\x00-\x1f]', environment):
            raise ValueError('填写 Windows Orca 中已配对的环境名称。')
        results = {}
        for kind in ('repo', 'terminal', 'host'):
            args = [str(orca_cli()), kind, 'list', '--json']
            if kind != 'host':
                args += ['--environment', environment.strip()]
            result = subprocess.run(args, capture_output=True, timeout=45, env=clean_env(), creationflags=0x08000000)
            try:
                value = json.loads(result.stdout.decode('utf-8-sig'))
            except ValueError:
                raise ValueError('Orca 未返回有效请求结果；检查配对和所选环境。') from None
            if result.returncode or value.get('ok', True) is False:
                raise ValueError('Orca 实际请求未成功；检查远程运行时、配对与环境名称。')
            results[kind] = value
        hosts = results['host'].get('hosts') or (results['host'].get('data') or {}).get('hosts') or []
        matched = False
        for host in hosts:
            labels = [host.get(key) for key in ('name', 'label', 'displayName', 'environment', 'id')]
            if environment in labels and expected and expected in json.dumps(host):
                matched = True
        return {'passed': matched, 'rpc_passed': True, 'host_matched': matched,
                'message': '项目与终端请求成功，目标 VPS 匹配。' if matched else
                '项目与终端请求成功；当前 CLI 未返回可自动匹配的目标地址，请核对环境对应的 VPS，尚不宣告目标身份验收完成。'}

    def install(self, body):
        root = source_root()
        if not root:
            raise ValueError('当前只含插件运行时。新机安装请运行完整 Orca Deploy 安装包，或从源码启动安装助手。')
        target = body.get('install_dir')
        if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z]:[\\/].+', target) or re.search(r'[\x00-\x1f]', target):
            raise ValueError('选择具体的本机应用目录，不能使用磁盘根目录。')
        directory = pathlib.Path(target).resolve()
        if directory == pathlib.Path(directory.anchor):
            raise ValueError('选择具体应用目录。')
        with self.lock:
            if self.busy:
                raise ValueError('本机安装任务仍在运行。')
            self.busy = True
        ident = uuid.uuid4().hex
        report = self.root / ('local-' + ident + '.json')
        atomic_json(report, {'id': ident, 'status': 'running', 'message': '正在准备本机组件。'})

        def run():
            try:
                env = clean_env()
                env['ORCA_DEPLOY_LOCAL_OPTIONS'] = base64.b64encode(json.dumps(
                    {'install_dir': str(directory), 'source_root': str(root), 'report': str(report)}).encode()).decode()
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(root / 'scripts/install-deploy-client.ps1')],
                                        capture_output=True, timeout=1800, env=env, creationflags=0x08000000)
                if result.returncode:
                    atomic_json(report, {'id': ident, 'status': 'needs-attention', 'message': '本机安装尚未完成；可能需要管理员确认或手动完成官方安装器。重新检查已有组件后继续。'})
            except Exception:
                atomic_json(report, {'id': ident, 'status': 'needs-attention', 'message': '本机安装未完成；检查组件状态后继续，未自动删除任何已有安装。'})
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=run, daemon=True).start()
        return {'id': ident, 'message': '本机安装任务已开始。需要时在 Windows 官方安装器和管理员弹窗中完成操作。'}

    def gpu_install(self, body):
        root = source_root()
        if not root:
            raise ValueError('GPU 安装需要完整安装包中的源码；已有插件可继续使用当前 GPU 管理。')
        config = pathlib.Path(body.get('settings', ''))
        if not config.is_absolute() or not config.is_file() or config.suffix != '.json':
            raise ValueError('选择本机已准备的 GPU 私有 JSON 配置文件。')
        result = subprocess.run([sys_executable(), str(root / 'scripts/install-local-gpu.py'), '--settings', str(config)],
                                capture_output=True, timeout=300, env=clean_env(), creationflags=0x08000000)
        if result.returncode:
            raise ValueError('GPU 安装未执行完成。若现有 Bridge 正在运行，请保留服务并使用当前管理页；不要为安装中断编辑器或任务。')
        return {'message': 'GPU Bridge 安装阶段完成；继续配置 VPS 每个账号的 MCP，并验证一次截图和回传。'}


def sys_executable():
    import sys
    return sys.executable
