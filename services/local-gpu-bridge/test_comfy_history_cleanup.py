import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import comfy_history_cleanup as cleanup


def completed(ts):
    return {'status':{'messages':[['execution_success', {'timestamp':ts}]]}}


class CleanupTests(unittest.TestCase):
    def test_partial_archive_remains_readable_and_last_expired_entry_removes_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'history.json.gz'
            rows = {'expired':completed(99), 'protected':completed(99), 'recent':completed(101)}
            with gzip.open(file, 'wt', encoding='utf-8') as f:
                json.dump(rows, f)
            self.assertEqual(cleanup.prune_archive(file, 100, {'protected'}), 1)
            with gzip.open(file, 'rt', encoding='utf-8') as f:
                self.assertEqual(json.load(f), {k:rows[k] for k in ('protected','recent')})
            self.assertEqual(cleanup.prune_archive(file, 101, set()), 2)
            self.assertFalse(file.exists())

    def test_scan_finishes_before_deletes_and_preserves_pending_or_unknown_records(self):
        calls = []
        pages = [{'old':completed(100), 'running':completed(1)},
                 {'protected':completed(1), 'unknown':{'status':{'messages':[]}}}, {}]
        def request(port, route, body=None):
            calls.append((route, body))
            if route.startswith('/history?'): return pages.pop(0)
            if route == '/queue': return {'queue_running':[[1, 'running']], 'queue_pending':[]}
        with patch.object(cleanup, 'request', request), patch.object(cleanup, 'PAGE_SIZE', 2):
            self.assertEqual(cleanup.prune_live(8188, 100, {'protected'}), 1)
        self.assertEqual(calls[-1], ('/history', {'delete':['old']}))
        self.assertEqual(len(calls), 5)
