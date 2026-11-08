"""Real Git integration in disposable fixtures; no personal repos or credentials."""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from broker import Broker, BrokerError, Project, Workspace, filtered, relative


@unittest.skipUnless(sys.platform == 'linux' and pathlib.Path('/usr/bin/git').is_file(), 'Linux Git fixture required')
class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orca-git-broker-test-')
        self.root = pathlib.Path(self.temp.name)
        self.seed = self.root / 'seed'
        self.store = self.root / 'store'
        self.store.mkdir(mode=0o700)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.upstream = self.root / 'upstream.git'
        self.git('init', '--initial-branch=main', str(self.seed))
        self.git('-C', str(self.seed), 'config', 'user.name', 'Fixture Author')
        self.git('-C', str(self.seed), 'config', 'user.email', 'private-canary@example.invalid')
        (self.seed / 'hello.txt').write_text('first\n')
        self.git('-C', str(self.seed), 'add', 'hello.txt')
        self.git('-C', str(self.seed), 'commit', '-m', 'initial private-canary@example.invalid')
        self.git('clone', '--bare', str(self.seed), str(self.upstream))
        self.git('clone', '--bare', str(self.upstream), str(self.store / 'repository.git'))
        self.project = {'repository': str(self.store / 'repository.git'), 'workspace': str(self.source),
                        'branch': 'main', 'agent_uid': os.getuid(), 'allow_write': True,
                        'author_name': 'Developer', 'author_email': 'broker-noreply@example.invalid'}
        self.broker = Broker({'store': str(self.store), 'projects': {'game': self.project}}, enforce_identity=False)
        instance = Project(self.project)
        try:
            for name, (content, mode) in instance.tree().items():
                instance.workspace.write(name, content, mode)
        finally:
            instance.workspace.close()
    def tearDown(self):
        self.temp.cleanup()
    def git(self, *args):
        env = {**os.environ, 'TZ': 'UTC0', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        result = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', *args], capture_output=True, env=env)
        if result.returncode:
            self.fail(result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()
    def call(self, operation, arguments=None, uid=None):
        return self.broker.handle(os.getuid() if uid is None else uid,
                                  {'project_id': 'game', 'operation': operation, 'arguments': arguments or {}})
    def test_fixed_operations_and_identity_rejection(self):
        with self.assertRaises(BrokerError):
            self.call('status', uid=os.getuid() + 999)
        for operation, args in [('config', {}), ('push', {'arbitrary': '--force'}), ('log', {'limit': 300})]:
            with self.subTest(operation=operation), self.assertRaises(BrokerError):
                self.call(operation, args)
    def test_history_identity_is_not_returned_or_rewritten(self):
        status = self.call('status')
        self.assertEqual(status['changes'], [])
        output = json.dumps(self.call('log'))
        self.assertNotIn('private-canary@example.invalid', output)
        original = self.git('--git-dir=' + self.project['repository'], 'log', '-1', '--format=%ae')
        self.assertEqual(original, 'private-canary@example.invalid')
    def test_commit_push_and_fast_forward_pull(self):
        before = self.call('status')['head']
        (self.source / 'hello.txt').write_text('changed\n')
        patch = self.call('diff')['patch']
        self.assertIn('+changed', patch)
        with self.assertRaises(BrokerError):
            self.call('commit', {'message': 'test', 'expected_head': None})
        commit = self.call('commit', {'message': 'safe update', 'expected_head': before})
        self.assertTrue(commit['committed'])
        self.assertEqual(self.call('status')['changes'], [])
        self.assertTrue(self.call('push', {'expected_head': commit['head']})['pushed'])
        self.assertEqual(self.git('--git-dir=' + str(self.upstream), 'rev-parse', 'refs/heads/main'), commit['head'])
        self.git('-C', str(self.seed), 'fetch', str(self.upstream), 'main')
        self.git('-C', str(self.seed), 'reset', '--hard', 'FETCH_HEAD')
        (self.seed / 'second.txt').write_text('remote update\n')
        self.git('-C', str(self.seed), 'add', 'second.txt')
        self.git('-C', str(self.seed), 'commit', '-m', 'remote update')
        self.git('-C', str(self.seed), 'push', str(self.upstream), 'main')
        result = self.call('pull', {'expected_head': commit['head']})
        self.assertTrue(result['updated'])
        self.assertEqual((self.source / 'second.txt').read_text(), 'remote update\n')
        self.assertEqual(self.call('status')['changes'], [])
    def test_dirty_pull_does_not_discard_and_links_are_refused(self):
        before = self.call('status')['head']
        (self.source / 'hello.txt').write_text('keep me\n')
        with self.assertRaises(BrokerError):
            self.call('pull', {'expected_head': before})
        self.assertEqual((self.source / 'hello.txt').read_text(), 'keep me\n')
        secret = self.store / 'private-config'
        secret.write_text('CANARY-SECRET')
        (self.source / 'linked').symlink_to(secret)
        with self.assertRaises((BrokerError, OSError)):
            self.call('diff')
        (self.source / 'linked').unlink()
        os.link(secret, self.source / 'hardlinked')
        with self.assertRaises(BrokerError):
            self.call('diff')
    def test_new_nested_export_is_agent_group_writable(self):
        workspace = Workspace(self.source)
        try:
            workspace.write('deep/path/file.txt', b'ok', '100644')
        finally:
            workspace.close()
        self.assertTrue((self.source / 'deep/path').stat().st_mode & 0o020)
    def test_bad_paths(self):
        for path in ('../secret', '/etc/passwd', '.git/config', '.env', 'x/../../z', 'x\nfile'):
            with self.subTest(path=path), self.assertRaises(BrokerError):
                relative(path)


if __name__ == '__main__':
    unittest.main()
