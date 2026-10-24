"""Start the locally configured ComfyUI once; never accept remote launch arguments."""
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request


def launch_spec(config):
    value = config.get('comfy_startup', {})
    if not value.get('enabled', False):
        return None
    url = urllib.parse.urlsplit(config.get('comfy_url', 'http://127.0.0.1:8188'))
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise ValueError('ComfyUI startup requires a loopback HTTP URL.')
    port = url.port or 80
    root = Path(value['root']).resolve(strict=True)
    python = Path(value['python']).resolve(strict=True)
    if not root.is_dir() or not python.is_file() or not (root / 'main.py').is_file():
        raise ValueError('ComfyUI startup installation is incomplete.')
    command = [str(python), '-X', 'utf8', str(root / 'main.py'), '--listen', '127.0.0.1', '--port', str(port)]
    for key, flag in [('model_paths_config', '--extra-model-paths-config'), ('input_directory', '--input-directory'), ('output_directory', '--output-directory')]:
        if value.get(key):
            target = Path(value[key]).resolve(strict=True)
            if key == 'model_paths_config' and not target.is_file() or key != 'model_paths_config' and not target.is_dir():
                raise ValueError('A ComfyUI startup path is invalid.')
            command += [flag, str(target)]
    return command, root, f'http://127.0.0.1:{port}'


def healthy(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/queue', timeout=2) as response:
            value = json.load(response)
        return isinstance(value.get('queue_running'), list) and isinstance(value.get('queue_pending'), list)
    except Exception:
        return False


def acquire(root):
    handle = (root / 'comfy-startup.lock').open('a+b')
    try:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def ensure(config, timeout=300):
    spec = launch_spec(config)
    if spec is None:
        return 'disabled'
    command, cwd, url = spec
    root = Path(config['data_dir']); root.mkdir(parents=True, exist_ok=True)
    lock = acquire(root)
    if lock is None:
        return 'starting'
    try:
        if healthy(url):
            return 'ready'
        # Do not repeatedly launch on an occupied port while a manual instance loads.
        import socket
        with socket.socket() as sock:
            sock.settimeout(1)
            occupied = sock.connect_ex(('127.0.0.1', urllib.parse.urlsplit(url).port)) == 0
        process = None
        if not occupied:
            with (root / 'comfy-startup.log').open('ab') as stream:
                flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
                process = subprocess.Popen(command, cwd=cwd, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                           stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                           creationflags=flags, shell=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if healthy(url):
                return 'ready'
            if process is not None and process.poll() is not None:
                raise RuntimeError('ComfyUI exited during startup. Inspect the local comfy-startup.log.')
            time.sleep(2)
        raise RuntimeError('ComfyUI startup is taking longer than expected. Inspect the local comfy-startup.log.')
    finally:
        lock.close()


def start_background(config):
    import threading
    def run():
        try:
            logging.info('ComfyUI startup: %s', ensure(config))
        except Exception:
            logging.exception('ComfyUI automatic startup failed')
    threading.Thread(target=run, daemon=True, name='comfy-startup').start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    logging.basicConfig(filename=Path(config['data_dir']) / 'comfy-launcher.log', level=logging.INFO)
    try:
        logging.info('ComfyUI startup: %s', ensure(config))
    except Exception:
        logging.exception('ComfyUI automatic startup failed')
        raise SystemExit(1)
