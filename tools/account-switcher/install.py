"""Install the account panel as a Linux user service, without copying OAuth credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if sys.platform != 'linux' or os.getuid() == 0:
        raise ValueError('Run as the non-root user that owns the Orca runtime.')
    source = Path(__file__).resolve().parent
    target = Path.home() / '.local/share/orca-tools/account-switcher'
    shutil.copytree(source / 'panel', target / 'panel', dirs_exist_ok=True)
    shutil.copy2(source / 'claude-account.py', target / 'claude-account.py')
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target / 'panel/claude-account-panel.service', units)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'claude-account-panel.service'], check=True)
    print('Account panel installed at http://127.0.0.1:18766/ on the remote host.')


if __name__ == '__main__':
    main()
