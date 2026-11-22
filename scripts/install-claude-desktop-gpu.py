"""Install the GPU MCP clients into Claude Desktop on Windows, preserving other servers."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

NAMESPACES = ('comfyui', 'godot', 'blender', 'vroid', 'tripo', 'unity')


def protect(folder):
    identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True,
                              capture_output=True, text=True).stdout
    import re
    sid = re.search(r'S-1-5-[0-9-]+', identity).group(0)
    subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r',
                    f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                   check=True, capture_output=True)


def desktop_configs():
    local = Path(os.environ['LOCALAPPDATA'])
    # New MSIX builds migrated userData out of the package's virtual Roaming dir.
    current = [p for p in (local/'Claude-Data').glob('claude_*')
               if p.is_dir() and (p/'config.json').is_file()]
    if current:
        return current
    store = list((local/'Packages').glob('Claude_*/LocalCache/Roaming/Claude'))
    normal = Path(os.environ['APPDATA'])/'Claude'
    if normal.is_dir(): store.append(normal)
    return store or [normal]


def merged_config(existing, root, python):
    value = dict(existing)
    servers = dict(value.get('mcpServers', {}))
    for namespace in NAMESPACES:
        servers['orca-gpu' if namespace == 'comfyui' else 'orca-'+namespace] = {
            'command': str(python),
            'args': [str(root/'client.py'), '--config', str(root/'client.json'), '--namespace', namespace],
            'env': {'PYTHONUTF8':'1'},
        }
    value['mcpServers'] = servers
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-client', type=Path, required=True)
    parser.add_argument('--client-config', type=Path, required=True)
    parser.add_argument('--install-dir', type=Path)
    args = parser.parse_args()
    if os.name != 'nt': raise SystemExit('This installer requires Windows.')
    root = args.install_dir or Path(os.environ['LOCALAPPDATA'])/'OrcaGpuClient'
    root.mkdir(parents=True, exist_ok=True); protect(root)
    config = json.loads(args.client_config.read_text(encoding='utf-8-sig'))
    # Validate endpoint and credential before changing Desktop's configuration.
    import importlib.util
    spec = importlib.util.spec_from_file_location('install_gpu_client', args.source_client)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.Client(args.client_config)
    destinations = desktop_configs()
    prepared = []
    for folder in destinations:
        target = folder/'claude_desktop_config.json'
        current = json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else {}
        prepared.append((target, merged_config(current, root, Path(sys.executable))))
    if args.source_client.resolve() != (root/'client.py').resolve():
        shutil.copyfile(args.source_client, root/'client.py')
    (root/'client.json').write_text(json.dumps(config, indent=2)+'\n', encoding='utf-8')
    for target, value in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            shutil.copyfile(target, root/('desktop-config-backup-'+stamp+'.json'))
        temp = target.with_suffix('.gpu-install.tmp')
        temp.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
        temp.replace(target)
    print(json.dumps({'installed':True,'servers':len(NAMESPACES),'desktop_configs':len(prepared)}))


if __name__ == '__main__': main()
