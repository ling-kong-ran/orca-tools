"""Tests the forced SSH reader against disposable local fixtures."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

reader = pathlib.Path(__file__).with_name('remote-reader.py')
job_id = 'a' * 32
with tempfile.TemporaryDirectory(prefix='orca-reader-test-') as folder:
    home = pathlib.Path(folder)
    source = home / 'source.bin'
    data = os.urandom(2048)
    source.write_bytes(data)
    info = source.stat()
    jobs = home / '.local/share/orca-parallel-download/jobs'
    jobs.mkdir(parents=True)
    job_path = jobs / (job_id + '.json')
    job_path.write_text(json.dumps({'source': str(source),
        'fingerprint': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns],
        'tag': 'orca-download:' + job_id}))
    keys = home / '.ssh/authorized_keys'
    keys.parent.mkdir()
    keys.write_text('PRESERVE_OTHER_KEY\nTEST orca-download:' + job_id + '\n')
    def call(command):
        env = dict(os.environ, HOME=folder, USERPROFILE=folder, SSH_ORIGINAL_COMMAND=command)
        return subprocess.run([sys.executable, str(reader), job_id], env=env, capture_output=True)
    result = call('read 19 70')
    assert result.returncode == 0 and result.stdout == data[19:89]
    for command in ['cat /etc/passwd', 'read -1 2', 'read 2047 2', 'read 0 8388609', 'read 0 12; rm -rf /']:
        result = call(command)
        assert result.returncode != 0 and result.stdout == b'', command
    source.write_bytes(data + b'changed')
    assert call('read 0 8').returncode != 0
    assert call('done').returncode == 0
    assert keys.read_text() == 'PRESERVE_OTHER_KEY\n' and not job_path.exists()
print('PASS: exact ranges, command rejection, bounds, changed-source rejection, scoped key cleanup.')
