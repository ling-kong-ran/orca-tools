"""Install the MCP source and private connection config for one Linux Claude profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-config', required=True, type=Path)
    parser.add_argument('--claude-config-dir', type=Path,
                        help='An existing Orca Claude profile; omit for the default profile')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.getuid() == 0:
        raise ValueError('Run as the non-root Orca/Claude worker user on the Linux VPS.')
    source = Path(__file__).resolve().parents[1] / 'services/local-gpu-bridge'
    # Resolve real OS home, matching client.py even when Orca isolates HOME per account.
    import pwd
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    root = home / '.local/share/orca-tools/local-gpu-marketplace'
    config_file = home / '.config/local-gpu-bridge/client.json'
    value = json.loads(args.client_config.read_text(encoding='utf-8-sig'))
    sys.path.insert(0, str(source / 'plugin'))
    from client import Client
    # Validate the endpoint and token before writing or invoking Claude.
    Client(args.client_config)
    value['require_private_tailnet_metadata'] = True
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'plugin', root / 'plugin', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(source / '.claude-plugin', root / '.claude-plugin', dirs_exist_ok=True)
    config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_file.parent.chmod(0o700)
    fd = os.open(config_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
    config_file.chmod(0o600)
    env = dict(os.environ)
    if args.claude_config_dir:
        profile = args.claude_config_dir.resolve(strict=True)
        env['CLAUDE_CONFIG_DIR'] = str(profile)
    for command in [
        ['claude', 'plugin', 'marketplace', 'add', str(root), '--scope', 'user'],
        ['claude', 'plugin', 'install', 'local-gpu@local-gpu-tools', '--scope', 'user'],
        ['claude', 'plugin', 'update', 'local-gpu@local-gpu-tools'],
        ['claude', 'plugin', 'enable', 'local-gpu@local-gpu-tools'],
    ]:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90)
        if result.returncode and 'already' not in (result.stdout + result.stderr).lower():
            raise RuntimeError('Claude plugin command failed: ' + ' '.join(command[:4]) +
                               '. Check claude plugin --help for this installed version.')
    print('Installed local-gpu. Run /reload-plugins in an existing Claude session.')


if __name__ == '__main__':
    main()
