"""Regression tests for uncertain submissions and idle Bridge resources."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from bridge import Bridge, ComfyAdapter
from render_capacity import RenderCapacity
from test_bridge import FakeAdapter


class LostReply(FakeAdapter):
    def submit(self, prompt, client_id):
        self.client_id = client_id
        self.prompt_id = super().submit(prompt, client_id)
        raise TimeoutError('ComfyUI accepted the prompt before the reply was lost')

    def find_submission(self, client_id):
        if client_id == self.client_id:
            return {'prompt_id': self.prompt_id, **self.inspect(self.prompt_id)}
        return None


class BridgeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root/'workflows').mkdir()
        (self.root/'workflows/connection-test.json').write_bytes(
            Path(__file__).with_name('example-workflow.json').read_bytes())
        self.config = {'data_dir': folder.name, 'native': {'render_concurrency': 1}}
        self.adapter = LostReply()
        self.bridge = Bridge(self.config, self.adapter)
        self.native = self.bridge.native
        self.native.capacity = RenderCapacity(1, probe=lambda: 4)
        self.ident = self.native.workspace('a'*32)['project_id']
        self.project = self.native.project(self.ident)[1]
        self.request = {'workflow_id': 'connection-test', 'parameters': {'color': 123},
                        'project_id': self.ident, 'request_id': 'b'*32}

    def test_lost_reply_retains_capacity_and_recovers_id_after_restart(self):
        with self.assertRaises(TimeoutError):
            self.bridge.submit(self.request)
        job = self.bridge.public(next(iter(self.bridge.jobs.values())))
        self.assertEqual(job['status'], 'unknown')
        self.assertEqual(self.native.capacity.status()['in_use'], 1)
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.bridge.submit({**self.request, 'request_id': 'c'*32})

        restored = Bridge(self.config, self.adapter)
        self.assertFalse(restored.native.capacity.project_available(self.project))
        self.assertEqual(restored.inspect(job['id'])['status'], 'queued')
        self.assertEqual(restored.jobs[job['id']]['prompt_id'], self.adapter.prompt_id)
        self.adapter.complete(self.adapter.prompt_id)
        self.assertEqual(restored.inspect(job['id'])['status'], 'succeeded')
        self.assertTrue(restored.native.capacity.project_available(self.project))
        self.assertEqual(restored.submit(self.request)['id'], job['id'])
        self.assertEqual(self.adapter.submissions, 1)

    def test_expired_unknown_needs_a_successful_search_before_releasing(self):
        with self.assertRaises(TimeoutError):
            self.bridge.submit(self.request)
        job = next(iter(self.bridge.jobs.values()))
        job['updated_at'] = time.time() - 121
        self.adapter.find_submission = Mock(side_effect=OSError('not reachable'))
        with self.assertRaises(OSError):
            self.bridge.inspect(job['id'])
        self.assertFalse(self.native.capacity.project_available(self.project))
        self.adapter.find_submission = Mock(return_value=None)
        self.assertEqual(self.bridge.inspect(job['id'])['status'], 'unknown')
        self.assertTrue(self.native.capacity.project_available(self.project))
        self.assertEqual(self.bridge.submit(self.request)['id'], job['id'])
        self.assertEqual(self.adapter.submissions, 1)

    def test_history_correlation_uses_existing_client_prefix_and_ignores_other_jobs(self):
        adapter = ComfyAdapter('http://127.0.0.1:8188')
        client_id = 'local-gpu-bridge-' + 'a'*32
        record = {'prompt': [0, 'own', {}, {'client_id': client_id}],
                  'status': {'completed': True}, 'outputs': {}}
        other = [0, 'other', {}, {'client_id': 'other'}]
        adapter.request = Mock(side_effect=[
            {'queue_running': [other], 'queue_pending': []}, {'own': record}])
        self.assertEqual(adapter.find_submission(client_id),
                         {'prompt_id': 'own', 'status': 'succeeded', 'artifacts': []})

    def test_reaping_only_closes_exited_editors(self):
        unity = self.native.unity.session(self.ident)
        unity.editor = Mock()
        unity.editor.poll.return_value = 0
        editor = unity.editor
        unity.close_rpc = Mock()
        unity.recovery_requests['request'] = {'started': True}
        vroid = self.native.vroid.session(self.project)
        vroid.process = Mock()
        vroid.process.poll.return_value = 0
        vroid_process = vroid.process
        blender = Mock()
        blender.poll.return_value = 0
        self.native.blenders[self.ident] = blender
        live = Mock()
        live.poll.return_value = None
        self.native.blenders['unrelated'] = live

        self.native.reap_editors()
        self.native.reap_editors()
        for process in (editor, vroid_process, blender):
            process.close.assert_called_once_with()
        unity.close_rpc.assert_called_once_with()
        self.assertIsNone(unity.editor)
        self.assertIn('request', unity.recovery_requests)
        self.assertIsNone(self.native.vroid.legacy_owner)
        live.close.assert_not_called()

    def test_cache_prune_preserves_workspace_and_user_output(self):
        library = self.project/'unity/Library'
        library.mkdir()
        output = self.project/'outputs/model.glb'
        output.write_bytes(b'asset')
        marker = self.project/'.last-used'
        now = time.time()
        os.utime(marker, (now - 8*86400, now - 8*86400))
        cutoff = now - 7*86400
        with self.native.capacity.operation(self.project):
            self.native.prune_workspace_caches(cutoff)
            self.assertTrue(library.is_dir())
        self.native.prune_workspace_caches(cutoff)
        self.assertFalse(library.exists())
        self.assertEqual(output.read_bytes(), b'asset')
        self.assertEqual(self.native.workspace('a'*32)['project_id'], self.ident)
        library.mkdir()
        self.native.prune_workspace_caches(cutoff)
        self.assertTrue(library.is_dir())
