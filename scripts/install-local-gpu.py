"""Install a configured Windows GPU bridge without embedding machine settings in Git."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'services/local-gpu-bridge'
FILES = ['bridge.py', 'comfy_startup.py', 'job_reuse.py', 'workflow_library.py', 'native_control.py', 'native_process.py',
         'native_git.py', 'native_script.py', 'native_godot.gd', 'native_blender.py', 'native_vroid.py',
         'Setup-Native-Privacy.ps1', 'manage.py', 'admin.py', 'admin.html']


def install(settings_file, start=True, startup=True):
    if os.name != 'nt':
        raise ValueError('Install this service on the Windows GPU computer.')
    settings = json.loads(Path(settings_file).read_text(encoding='utf-8-sig'))
    tailnet = ipaddress.ip_network('100.64.0.0/10')
    if ipaddress.ip_address(settings['listen']) not in tailnet:
        raise ValueError('listen must be this computer\'s Tailscale IPv4 address.')
    peers = settings['allowed_peers']
    if not peers or any(ipaddress.ip_address(p) not in tailnet for p in peers):
        raise ValueError('allowed_peers must contain only approved Tailscale IPv4 addresses.')
    root = Path(os.environ['LOCALAPPDATA']) / 'LocalGpuBridge'
    # Existing running installations must be stopped deliberately, not overwritten mid-render.
    if (root / 'process.json').exists():
        process = json.loads((root / 'process.json').read_text())
        check = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                f"if(Get-Process -Id {int(process['pid'])} -ErrorAction SilentlyContinue){{exit 1}}"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if check.returncode:
            raise ValueError('Bridge is running. Finish jobs and stop the bridge before upgrading.')
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise ValueError('Use a Windows Python installation containing pythonw.exe.')
    native = dict(settings.get('native', {}))
    native['git_only_sync'] = True
    native.setdefault('git_executable', shutil.which('git') or 'git')
    for project in native.get('projects', []):
        project_root = Path(project['root']).resolve(strict=True)
        if not project_root.is_dir() or project_root.parent == project_root:
            raise ValueError('Approve a specific existing project directory.')
        project['root'] = str(project_root)
    # Copy only the executables to names covered by the renderer firewall rules.
    # Keep Blender beside its DLLs/data, and Go inside the selected Go installation.
    managed = {'godot_executable': 'Godot-LocalGpu.exe',
               'blender_executable': 'blender-local-gpu.exe', 'go_executable': 'go-local-gpu.exe'}
    copies = []
    for key, name in managed.items():
        if native.get(key):
            original = Path(native[key]).resolve(strict=True)
            if not original.is_file():
                raise ValueError('Renderer/compiler must be an executable file.')
            target = original.with_name(name)
            copies.append((original, target))
            native[key] = str(target)
    for directory in settings.get('workflow_dirs', []):
        if not Path(directory).is_dir():
            raise ValueError('A configured workflow directory does not exist.')
    if native.get('go_executable'):
        # Capture cache locations before offline builds intentionally disable GOENV.
        query_env={**os.environ,'GOTOOLCHAIN':'local','GOPROXY':'off','GOFLAGS':''}
        if native.get('go_root'):query_env['GOROOT']=native['go_root']
        original_go=next(original for original,target in copies if str(target)==native['go_executable'])
        query=subprocess.run([str(original_go),'env','-json','GOPATH','GOMODCACHE','GOCACHE','GOROOT'],env=query_env,
                             capture_output=True,text=True,encoding='utf-8',timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        if query.returncode:raise ValueError('Cannot resolve local Go paths. Configure native.go_root for the selected compiler.')
        paths=json.loads(query.stdout)
        for setting,variable in [('go_module_cache','GOMODCACHE'),('go_build_cache','GOCACHE'),('go_root','GOROOT')]:
            native.setdefault(setting,paths[variable])
    sys.path.insert(0, str(SOURCE))
    from comfy_startup import launch_spec
    launch_spec(settings)
    (root / 'app').mkdir(parents=True, exist_ok=True)
    (root / 'workflows').mkdir(exist_ok=True)
    config_file = root / 'config.json'
    previous = json.loads(config_file.read_text()) if config_file.exists() else {}
    # The optional Studio installer adds a managed copy after the base install.
    # Retain it when upgrading from the original connection settings file.
    managed_vroid = root / 'native/vroid/VRoidStudio-LocalGpu.exe'
    if 'vroid_executable' not in native and managed_vroid.is_file() and previous.get('native', {}).get('vroid_executable') == str(managed_vroid):
        native['vroid_executable'] = str(managed_vroid)
    config = {**settings, 'token': previous.get('token') or secrets.token_hex(32),
              'data_dir': str(root), 'port': 18772, 'admin_port': 18773,
              'auto_setup_privacy': bool(copies or native.get('vroid_executable')), 'native': native}
    config.setdefault('comfy_url', 'http://127.0.0.1:8188')
    # Game-server binaries are always placed under the bridge, never at arbitrary paths.
    native['server_executables'] = {
        p['id']: str(root / 'native/servers' / (p['id'] + '.exe'))
        for p in native.get('projects', []) if native.get('go_executable')}
    if config_file.exists():
        shutil.copy2(config_file, root / 'config.previous.local.json')
    for original, target in copies:
        if original != target:
            shutil.copy2(original, target)
    for name in FILES:
        shutil.copy2(SOURCE / name, root / 'app' / name)
    config_file.write_text(json.dumps(config, indent=2), encoding='utf-8')
    (root / 'launcher.json').write_text(json.dumps({'pythonw': str(pythonw)}), encoding='utf-8')
    # This is the ONLY secret file to transfer privately to the VPS. Never commit it.
    export = {'url': f"http://{settings['listen']}:18772", 'token': config['token'],
              'require_private_tailnet_metadata': True}
    (root / 'client.local.json').write_text(json.dumps(export, indent=2), encoding='utf-8')
    command = subprocess.list2cmdline([str(pythonw), str(root / 'app/bridge.py'), '--config', str(config_file)])
    if startup:
        folder = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'Local GPU Bridge.vbs').write_text(
            'Set bridgeShell = CreateObject("WScript.Shell")\r\nbridgeShell.Run "' +
            command.replace('"', '""') + '", 0, False\r\n', encoding='utf-8')
    if start:
        subprocess.Popen([str(pythonw), str(root / 'app/bridge.py'), '--config', str(config_file)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    print('Installed. Manager: http://127.0.0.1:18773/')
    print('Private VPS configuration:', root / 'client.local.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--no-startup', action='store_true')
    args = parser.parse_args()
    install(args.settings, not args.no_start, not args.no_startup)
