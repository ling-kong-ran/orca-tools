"""Per-download, read-only forced SSH command. No arbitrary shell commands."""
import hashlib
import json
import os
import pathlib
import re
import shlex
import stat
import sys


def atomic_json(path, value):
    temp = path.with_suffix('.tmp-' + str(os.getpid()))
    with temp.open('x') as stream:
        json.dump(value, stream)
    temp.chmod(0o600)
    temp.replace(path)


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def register(request):
    job_id = request['id']
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid job ID')
    source = pathlib.Path(request['source']).resolve(strict=True)
    info = source.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Select a regular file')
    public_key = request['publicKey'].strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [a-zA-Z0-9:_-]+)?', public_key):
        raise ValueError('Invalid public key')
    host_key = pathlib.Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip().split()
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if fingerprint(source.stat()) != fingerprint(info):
        raise ValueError('Source changed while preparing download')
    root = pathlib.Path.home() / '.local/share/orca-parallel-download'
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    (root / 'jobs').mkdir(mode=0o700, exist_ok=True)
    job = {'source': str(source), 'fingerprint': fingerprint(info), 'tag': 'orca-download:' + job_id}
    atomic_json(root / 'jobs' / (job_id + '.json'), job)
    keys = pathlib.Path.home() / '.ssh/authorized_keys'
    script = pathlib.Path(__file__).resolve()
    command = 'python3 ' + shlex.quote(str(script)) + ' ' + job_id
    line = 'restrict,command="' + command.replace('"', '\\"') + '" ' + public_key
    existing = keys.read_text() if keys.exists() else ''
    with keys.open('a') as stream:
        stream.write(('\n' if existing and not existing.endswith('\n') else '') + line + '\n')
    keys.chmod(0o600)
    return {'size': info.st_size, 'sha256': digest.hexdigest(), 'source': str(source),
            'hostKey': ' '.join(host_key[:2]), 'fingerprint': fingerprint(info)}


def main():
    job_id = sys.argv[1]
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid job ID')
    path = pathlib.Path.home() / '.local/share/orca-parallel-download/jobs' / (job_id + '.json')
    job = json.loads(path.read_text())
    args = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if args == ['done']:
        keys = pathlib.Path.home() / '.ssh/authorized_keys'
        lines = keys.read_text().splitlines(keepends=True)
        remaining = ''.join(line for line in lines if job['tag'] not in line)
        temp = keys.with_suffix('.orca-' + job_id)
        temp.write_text(remaining)
        temp.chmod(0o600)
        temp.replace(keys)
        path.unlink()
        print('KEY_REMOVED')
        return
    if len(args) != 3 or args[0] != 'read':
        raise ValueError('Only bounded reads are allowed')
    offset, count = int(args[1]), int(args[2])
    source = pathlib.Path(job['source'])
    with source.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if fingerprint(info) != job['fingerprint']:
            raise ValueError('Source changed; create a new download')
        if offset < 0 or count < 1 or count > 8 * 1024 * 1024 or offset + count > info.st_size:
            raise ValueError('Invalid byte range')
        stream.seek(offset)
        while count:
            block = stream.read(min(count, 256 * 1024))
            if not block:
                raise ValueError('Unexpected end of file')
            sys.stdout.buffer.write(block)
            count -= len(block)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)
