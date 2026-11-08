"""Boundary tests: credentials, approval, resumability, concurrency and HTTP CSRF."""
import io
import calendar
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from engine import Engine
from plan import validate


class FakeTransport:
    wait = None
    calls = []
    def __init__(self, plan, identity, **credentials):
        self.credentials = credentials
    def close(self):
        pass
    def stage(self, operation, plan):
        self.calls.append(operation)
        if self.wait:
            self.wait.wait(3)
        if operation == 'inspect':
            return {'supported': True, 'enough_disk': True, 'enough_memory': True, 'needs_orca_package': False}
        if operation == 'verify':
            return {'server_passed': False, 'checks': {'account_registered': False}}
        return {'reused': True}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        FakeTransport.wait = None
        FakeTransport.calls = []
        self.engine = Engine(self.root, transport_factory=FakeTransport, probe_function=lambda p: {'fingerprint': 'SHA256:tested'})
        self.record = self.engine.create({'host': '100.64.0.20'})
        self.ident = self.record['id']
    def tearDown(self):
        if FakeTransport.wait:
            FakeTransport.wait.set()
        self.complete()
        self.engine.close()
        self.temp.cleanup()
    def complete(self):
        deadline = time.monotonic() + 5
        while self.ident in self.engine.busy and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertNotIn(self.ident, self.engine.busy)
    def connect(self):
        return self.engine.connect(self.ident, 'SHA256:tested', True, password='SECRET-MUST-NOT-PERSIST')
    def inspect(self):
        self.connect()
        self.engine.start(self.ident, 'inspect')
        self.complete()
        return self.engine.load(self.ident)
    def test_nonsecret_plan_only_and_private_host_validation(self):
        for value in ({'token': 'secret'}, {'password': 'secret'}, {'host': '127.0.0.1'},
                      {'host': '8.8.8.8'}, {'runtime_user': 'root'}, {'ssh_user': 'root;touch bad'},
                      {'connection': 'ssh', 'host': '8.8.8.8'}, {'client_tailnet_ip': '8.8.8.8'},
                      {'orca_asset_url': 'https://evil.invalid/fake.deb'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)
        self.assertEqual(validate({'host': '100.64.0.20'})['runtime_user'], 'workspace')
    def test_approval_required_and_secrets_absent_from_disk_and_export(self):
        with self.assertRaisesRegex(ValueError, '指纹'):
            self.engine.connect(self.ident, 'SHA256:tested', False)
        current = self.inspect()
        with self.assertRaises(ValueError):
            self.engine.start(self.ident, 'apply', 'stale-hash')
        self.engine.start(self.ident, 'apply', current['plan_hash'])
        self.complete()
        self.assertEqual(self.engine.load(self.ident)['status'], 'needs-authorization')
        self.assertEqual(FakeTransport.calls, ['inspect', 'system', 'tailscale', 'tools'])
        for file in self.root.glob('*.json'):
            self.assertNotIn('SECRET-MUST-NOT-PERSIST', file.read_text())
        with zipfile.ZipFile(io.BytesIO(self.engine.export(self.ident))) as archive:
            for name in archive.namelist():
                self.assertNotIn(b'SECRET-MUST-NOT-PERSIST', archive.read(name))
            self.assertIn('local.py', archive.namelist())
            self.assertIn('git-broker/broker.py', archive.namelist())
    def test_process_shared_destination_lock(self):
        self.connect()
        FakeTransport.wait = threading.Event()
        self.engine.start(self.ident, 'inspect')
        second = Engine(self.root, transport_factory=FakeTransport)
        try:
            other = second.create({'host': '100.64.0.20'})
            second.connect(other['id'], 'SHA256:tested', True)
            with self.assertRaises(ValueError):
                second.start(other['id'], 'inspect')
            self.assertEqual(second.load(self.ident)['status'], 'running')
        finally:
            second.close()
            FakeTransport.wait.set()
    def test_incomplete_verification_does_not_become_success(self):
        self.connect()
        self.engine.start(self.ident, 'verify')
        self.complete()
        self.assertEqual(self.engine.load(self.ident)['status'], 'needs-attention')
    def test_agent_export_omits_client_identity_paths_and_zip_uses_utc(self):
        current = self.engine.load(self.ident)
        current['plan']['install_dir'] = 'C:/Users/PRIVATE-PERSON/tools'
        current['plan']['environment'] = 'PRIVATE-CONNECTION-LABEL'
        self.engine.save(current)
        with zipfile.ZipFile(io.BytesIO(self.engine.export(self.ident))) as package:
            for name in ('DEPLOY.md', 'deploy-plan.json'):
                value = package.read(name)
                self.assertNotIn(b'PRIVATE-PERSON', value)
                self.assertNotIn(b'PRIVATE-CONNECTION-LABEL', value)
            stamps = {info.date_time for info in package.infolist()}
            self.assertEqual(len(stamps), 1)
            self.assertLess(abs(calendar.timegm(next(iter(stamps)) + (0, 0, 0)) - time.time()), 5)
    def test_restart_rechecks_uncertain_step(self):
        current = self.engine.load(self.ident)
        current.update(status='running', worker_pid=2147483646)
        self.engine.save(current)
        self.assertEqual(self.engine.load(self.ident)['status'], 'needs-inspection')
    def test_http_denies_wrong_origin_token_host_and_unknown_mutation(self):
        process = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).with_name('deploy.py')),
                                    '--data-dir', str(self.root / 'http'), 'serve', '--parent-stdio'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            endpoint = json.loads(process.stdout.readline())
            url = endpoint['url']
            def request(route, body, headers):
                req = urllib.request.Request(url + route, data=json.dumps(body).encode(), headers=headers)
                return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)
            headers = {'Content-Type': 'application/json', 'X-Toolkit-Token': endpoint['token'], 'Origin': url.rstrip('/')}
            for wrong in ({**headers, 'Origin': 'https://foreign.invalid'}, {**headers, 'X-Toolkit-Token': 'wrong'},
                          {**headers, 'Host': 'foreign.invalid'}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('api/deploy/create', {'plan': {}}, wrong)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            with request('api/deploy/create', {'plan': {'host': '100.64.0.20'}}, headers) as response:
                result = json.load(response)
                self.assertEqual(result['status'], 'draft')
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('api/deploy/exec', {'command': 'arbitrary shell'}, headers)
            error.exception.close()
        finally:
            process.stdin.close()
            process.wait(timeout=8)
            process.stdout.close()
            process.stderr.close()


if __name__ == '__main__':
    unittest.main()
