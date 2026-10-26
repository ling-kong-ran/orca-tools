"""Exercise installation into disposable folders without starting services or changing firewall."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('install-local-gpu.py'))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@unittest.skipUnless(os.name == 'nt', 'Windows installer')
class InstallTests(unittest.TestCase):
    def test_private_config_portable_launcher_and_token_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / 'Local'
            roaming = root / 'Roaming'
            project = root / 'project'
            project.mkdir()
            python = root / 'python.exe'
            python.touch()
            python.with_name('pythonw.exe').touch()
            godot = root / 'Godot.exe'
            godot.write_bytes(b'fixture renderer')
            settings = root / 'settings.local.json'
            settings.write_text(json.dumps({
                'listen': '100.64.0.10', 'allowed_peers': ['100.64.0.20'],
                'native': {'godot_executable': str(godot), 'projects': [
                    {'id': 'game', 'root': str(project), 'enabled': True}]}}))
            with patch.dict(os.environ, {'LOCALAPPDATA': str(local), 'APPDATA': str(roaming)}), \
                 patch.object(installer.sys, 'executable', str(python)), \
                 patch.object(installer.subprocess, 'Popen') as spawn:
                installer.install(settings, start=False)
                installed = local / 'LocalGpuBridge'
                first = json.loads((installed / 'config.json').read_text())
                self.assertTrue(first['native']['git_only_sync'])
                self.assertEqual(Path(first['native']['godot_executable']).read_bytes(), b'fixture renderer')
                client = json.loads((installed / 'client.local.json').read_text())
                self.assertEqual(client['token'], first['token'])
                self.assertTrue(client['require_private_tailnet_metadata'])
                self.assertGreaterEqual(len(client['token']), 32)
                launcher = json.loads((installed / 'launcher.json').read_text())
                self.assertEqual(launcher['pythonw'], str(python.with_name('pythonw.exe')))
                startup = roaming / 'Microsoft/Windows/Start Menu/Programs/Startup/Local GPU Bridge.vbs'
                self.assertIn('bridge.py', startup.read_text())
                installer.install(settings, start=False)
                second = json.loads((installed / 'config.json').read_text())
                self.assertEqual(first['token'], second['token'])
                self.assertTrue((installed / 'config.previous.local.json').exists())
                managed_vroid = installed / 'native/vroid/VRoidStudio-LocalGpu.exe'
                managed_vroid.parent.mkdir(parents=True); managed_vroid.touch()
                second['native']['vroid_executable'] = str(managed_vroid)
                (installed / 'config.json').write_text(json.dumps(second))
                installer.install(settings, start=False)
                third = json.loads((installed / 'config.json').read_text())
                self.assertEqual(third['native']['vroid_executable'], str(managed_vroid))
                self.assertTrue(third['auto_setup_privacy'])
                spawn.assert_not_called()

    def test_public_endpoint_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'bad.local.json'
            settings.write_text(json.dumps({'listen': '8.8.8.8', 'allowed_peers': []}))
            with self.assertRaisesRegex(ValueError, 'Tailscale'):
                installer.install(settings, start=False, startup=False)

    def test_go_user_cache_paths_are_captured_for_offline_builds(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);python=root/'python.exe';python.touch();python.with_name('pythonw.exe').touch()
            go=root/'go.exe';go.write_bytes(b'fixture compiler');sdk=root/'sdk';sdk.mkdir()
            paths={'GOROOT':str(sdk),'GOPATH':str(root/'workspace'),'GOMODCACHE':str(root/'modules'),'GOCACHE':str(root/'cache')}
            source=root/'settings.local.json'
            source.write_text(json.dumps({'listen':'100.64.0.10','allowed_peers':['100.64.0.20'],'native':{'go_executable':str(go),'go_root':str(sdk),'projects':[]}}))
            with patch.dict(os.environ,{'LOCALAPPDATA':str(root/'Local'),'APPDATA':str(root/'Roaming')}), \
                 patch.object(installer.sys,'executable',str(python)), \
                 patch.object(installer.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(paths),'')) as query:
                installer.install(source,start=False,startup=False)
                config=json.loads((root/'Local/LocalGpuBridge/config.json').read_text())
                self.assertEqual(config['native']['go_module_cache'],paths['GOMODCACHE'])
                self.assertEqual(config['native']['go_build_cache'],paths['GOCACHE'])
                self.assertEqual(query.call_args.kwargs['env']['GOPROXY'],'off')


if __name__ == '__main__':
    unittest.main()
