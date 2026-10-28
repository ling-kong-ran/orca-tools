"""Sign in to Tripo Studio once, by hand, in the bridge's dedicated browser profile (Windows only).

The plugin later reuses that profile headless to read the signed-in session; no password is stored.
Run it while no Tripo workflow is starting: it stops the plugin's background service first.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/local-gpu-bridge'))
from native_tripo import TripoControl  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get('LOCALAPPDATA', '')) / 'LocalGpuBridge/config.json'
    parser.add_argument('--config', type=Path, default=default, help='Local GPU Bridge config.json')
    parser.add_argument('--region', choices=['global', 'cn'], help='Override tripo.region from the config')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8')) if args.config.is_file() else {}
    if args.region: config['tripo'] = {**(config.get('tripo') or {}), 'region': args.region}
    control = TripoControl(config)
    print(f'Opening {control.site["studio"]} in the dedicated profile. Sign in, then close the window.')
    try: control.open_login().wait()
    finally: control.end_login()
    print('Done. The bridge starts Tripo Studio again within a minute and reuses this session.')


if __name__ == '__main__':
    main()
