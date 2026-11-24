"""Expire completed ComfyUI history on the local GPU host. Outputs stay on disk."""
import argparse
import gzip
import http.client
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.parse


RETENTION_SECONDS = 7 * 86400
PAGE_SIZE = 100
TERMINAL_EVENTS = {'execution_success', 'execution_error', 'execution_interrupted'}


def expired(record, cutoff_ms):
    messages = record.get('status', {}).get('messages', [])
    finished = [event[1].get('timestamp') for event in messages
                if isinstance(event, list) and len(event) == 2
                and event[0] in TERMINAL_EVENTS and isinstance(event[1], dict)]
    return bool(finished) and all(type(t) in (int, float) and math.isfinite(t)
                                  and 0 < t <= cutoff_ms for t in finished)


def protected_prompts(root):
    protected = set()
    for file in (root / 'jobs').glob('*.json'):
        job = json.loads(file.read_bytes())
        if (job.get('status') not in ('succeeded', 'failed', 'cancelled')
                or job['status'] == 'succeeded' and not job.get('artifacts')):
            protected.add(job.get('prompt_id'))
    return protected


def prune_archive(file, cutoff_ms, protected):
    with gzip.open(file, 'rt', encoding='utf-8') as stream:
        history = json.load(stream)
    keep = {key: row for key, row in history.items() if key in protected or not expired(row, cutoff_ms)}
    removed = len(history) - len(keep)
    if removed and not keep:
        file.unlink()
    elif removed:
        with tempfile.NamedTemporaryFile(dir=file.parent, delete=False) as tmp:
            pending = Path(tmp.name)
        try:
            with gzip.open(pending, 'wt', encoding='utf-8') as stream:
                json.dump(keep, stream, ensure_ascii=False, separators=(',', ':'))
            os.replace(pending, file)
        finally:
            pending.unlink(missing_ok=True)
    return removed


def request(port, route, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        data = json.dumps(body).encode() if body is not None else None
        conn.request('POST' if data is not None else 'GET', route, data,
                     {'Content-Type':'application/json'})
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f'ComfyUI returned HTTP {response.status}.')
        return json.load(response) if data is None else None
    finally:
        conn.close()


def prune_live(port, cutoff_ms, protected):
    candidates = set()
    offset = 0
    while True:
        page = request(port, f'/history?max_items={PAGE_SIZE}&offset={offset}')
        candidates.update(key for key, row in page.items() if key not in protected and expired(row, cutoff_ms))
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    if candidates:
        queue = request(port, '/queue')
        for kind in ('queue_running', 'queue_pending'):
            candidates.difference_update(item[1] for item in queue[kind])
        ids = sorted(candidates)
        for start in range(0, len(ids), PAGE_SIZE):
            request(port, '/history', {'delete':ids[start:start + PAGE_SIZE]})
    return len(candidates)


def cleanup(config):
    root = Path(config['data_dir'])
    url = urllib.parse.urlsplit(config.get('comfy_url', 'http://127.0.0.1:8188'))
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path not in ('', '/'):
        raise ValueError('History cleanup requires a local ComfyUI HTTP endpoint.')
    cutoff = (time.time() - RETENTION_SECONDS) * 1000
    protected = protected_prompts(root)
    archived = sum(prune_archive(file, cutoff, protected)
                   for file in (root / 'deployment-backups').glob('comfy-threads-*/history.json.gz'))
    live = prune_live(url.port or 80, cutoff, protected)
    return {'archive_expired':archived, 'live_expired':live}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(cleanup(json.loads(args.config.read_bytes()))))
