import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import comfy_startup as startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.python = self.root / 'python.exe'; self.python.touch()
        (self.root / 'main.py').touch()
        self.config = {'data_dir': str(self.root), 'comfy_url': 'http://127.0.0.1:8188',
                       'comfy_startup': {'enabled': True, 'root': str(self.root), 'python': str(self.python)}}

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_and_invalid_configuration(self):
        self.assertEqual(startup.ensure({}), 'disabled')
        for url in ['http://0.0.0.0:8188', 'https://127.0.0.1:8188', 'http://127.0.0.1:8188/path', 'http://user@127.0.0.1:8188']:
            with self.assertRaises(ValueError):
                startup.launch_spec({**self.config, 'comfy_url': url})
        command, _, _ = startup.launch_spec(self.config)
        self.assertEqual(command[-4:], ['--listen', '127.0.0.1', '--port', '8188'])

    def test_existing_instance_and_concurrent_launcher_are_not_duplicated(self):
        with patch.object(startup, 'healthy', return_value=True), patch.object(startup.subprocess, 'Popen') as spawn:
            self.assertEqual(startup.ensure(self.config), 'ready'); spawn.assert_not_called()
        first = startup.acquire(self.root)
        try:
            self.assertIsNone(startup.acquire(self.root))
            self.assertEqual(startup.ensure(self.config), 'starting')
        finally:
            first.close()

    def test_successful_start_uses_fixed_arguments_and_no_shell(self):
        sock = MagicMock(); sock.__enter__.return_value.connect_ex.return_value = 1
        process = MagicMock(); process.poll.return_value = None
        with patch('socket.socket', return_value=sock), patch.object(startup, 'healthy', side_effect=[False, False, True]), \
             patch.object(startup.subprocess, 'Popen', return_value=process) as spawn, patch.object(startup.time, 'sleep'):
            self.assertEqual(startup.ensure(self.config), 'ready')
            self.assertEqual(spawn.call_count, 1)
            self.assertFalse(spawn.call_args.kwargs['shell'])
            self.assertEqual(spawn.call_args.args[0][-3:], ['127.0.0.1', '--port', '8188'])

    def test_occupied_port_is_not_replaced_and_failed_process_is_not_retried(self):
        sock = MagicMock(); sock.__enter__.return_value.connect_ex.return_value = 0
        with patch('socket.socket', return_value=sock), patch.object(startup, 'healthy', side_effect=[False, True]), \
             patch.object(startup.subprocess, 'Popen') as spawn:
            self.assertEqual(startup.ensure(self.config), 'ready'); spawn.assert_not_called()
        sock.__enter__.return_value.connect_ex.return_value = 1
        process = MagicMock(); process.poll.return_value = 1
        with patch('socket.socket', return_value=sock), patch.object(startup, 'healthy', return_value=False), \
             patch.object(startup.subprocess, 'Popen', return_value=process) as spawn:
            with self.assertRaisesRegex(RuntimeError, 'exited'):
                startup.ensure(self.config)
            self.assertEqual(spawn.call_count, 1)


if __name__ == '__main__':
    unittest.main()
