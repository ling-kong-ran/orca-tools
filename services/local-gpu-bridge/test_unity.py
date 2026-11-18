import json
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from native_unity import UnityControl, DENIED, preserve_scene_backups, startup_lock


class FakeEditor:
    def __init__(self): self.alive=True
    def poll(self): return None if self.alive else 0
    def stop(self): self.alive=False
    def close(self): self.alive=False


class UnityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        for part in ('Assets','Packages','ProjectSettings'): (self.root/part).mkdir()
        self.config={'native':{'unity_executable':str(self.root/'Unity-LocalGpu.exe'),
            'unity_cli_executable':str(self.root/'unity-cli-local-gpu.exe'),'unity_data_dir':str(self.root/'data')}}
        self.guard=types.SimpleNamespace(require=lambda engine:None,ready=lambda engine:True)
        self.calls=[]
        def process(*args,**kwargs): self.calls.append((args,kwargs));return FakeEditor()
        self.native=types.SimpleNamespace(config=self.config,root=self.root,guard=self.guard,
            project=lambda ident: ({'id':ident},self.root),process_factory=process)
        self.control=UnityControl(self.native);self.addCleanup(self.control.close_rpc)

    def test_managed_editor_pins_project_and_keeps_graphics_enabled(self):
        result=self.control.start('approved')
        self.assertTrue(result['started']);args,kwargs=self.calls[0]
        self.assertEqual(args[0][args[0].index('-projectPath')+1],str(self.root))
        self.assertNotIn('-nographics',args[0]);self.assertEqual(kwargs['process_limit'],128)
        self.assertTrue(self.control.start('approved')['already_running'])
        with self.assertRaises(ValueError):self.control.start('different')
        self.control.stop('approved');self.assertFalse(self.control.status()['connected'])

    def test_network_guard_and_real_project_required(self):
        self.guard.require=lambda engine:(_ for _ in ()).throw(ValueError('not isolated'))
        with self.assertRaisesRegex(ValueError,'not isolated'):self.control.start('approved')
        self.assertFalse(self.calls)
        (self.root/'Assets').rmdir()
        with self.assertRaisesRegex(ValueError,'not a Unity project'):self.control.project('approved')

    def test_scene_recovery_preserves_existing_scenes_and_all_backup_bytes(self):
        old=self.root/'Assets/_Recovery';old.mkdir();(old/'0.unity').write_bytes(b'old scene')
        backups=self.root/'Temp/__Backupscenes';backups.mkdir(parents=True)
        (backups/'0.backup').write_bytes(b'new unsaved scene')
        (backups/'notes').write_bytes(b'metadata')
        result=self.control.start('approved')
        self.assertEqual(result['recovered_scenes'],1)
        self.assertFalse(backups.exists())
        self.assertEqual((old/'0.unity').read_bytes(),b'old scene')
        saved=list(old.glob('bridge-*'));self.assertEqual(len(saved),1)
        self.assertEqual((saved[0]/'0.unity').read_bytes(),b'new unsaved scene')
        self.assertEqual((saved[0]/'notes').read_bytes(),b'metadata')
        self.control.stop('approved')
        self.assertEqual(self.control.start('approved')['recovered_scenes'],0)

    def test_scene_recovery_does_not_touch_a_locked_project(self):
        backups=self.root/'Temp/__Backupscenes';backups.mkdir(parents=True)
        (backups/'0.backup').write_bytes(b'live scene')
        with startup_lock(self.root):
            with self.assertRaisesRegex(ValueError,'locked'):
                self.control.start('approved')
        self.assertFalse(self.calls)
        self.assertEqual((backups/'0.backup').read_bytes(),b'live scene')

    def test_scene_recovery_does_not_overwrite_colliding_files(self):
        backups=self.root/'Temp/__Backupscenes';backups.mkdir(parents=True)
        (backups/'0.backup').write_bytes(b'backup')
        (backups/'0.unity').write_bytes(b'existing')
        self.assertEqual(preserve_scene_backups(self.root),1)
        saved=next((self.root/'Assets/_Recovery').glob('bridge-*'))
        self.assertEqual((saved/'0.backup').read_bytes(),b'backup')
        self.assertEqual((saved/'0.unity').read_bytes(),b'existing')

    def test_running_editor_without_pipeline_is_not_connected(self):
        self.control.start('approved')
        self.assertTrue(self.control.status()['running'])
        self.assertFalse(self.control.status()['connected'])
        self.control.rpc_process=types.SimpleNamespace(poll=lambda:None)
        with patch.object(self.control,'ensure_rpc'),patch.object(self.control,'_send',return_value={'tools':[{'name':'unity-cli-status'}]}):
            self.assertFalse(self.control.tools('approved')['ready'])
        with patch.object(self.control,'ensure_rpc'),patch.object(self.control,'_send',return_value={'tools':[{'name':'scene_info'}]}):
            self.assertTrue(self.control.tools('approved')['ready'])
            self.assertTrue(self.control.status()['connected'])
        with patch.object(self.control,'ensure_rpc'),patch.object(self.control,'_send',side_effect=ValueError('disconnected')):
            with self.assertRaises(ValueError):self.control.tools('approved')
            self.assertFalse(self.control.status()['connected'])
        self.control.rpc_process=None

    def test_no_desktop_fallback_or_inherited_credentials(self):
        with patch.dict('os.environ',{'CLAUDE_SECRET':'hidden','API_KEY':'hidden','UNITY_MCP_DESKTOP_FALLBACK':'1'}):
            env=self.control.environment()
        self.assertNotIn('API_KEY',env);self.assertNotIn('CLAUDE_SECRET',env)
        self.assertNotIn('UNITY_MCP_DESKTOP_FALLBACK',env);self.assertEqual(env['TZ'],'UTC')
        self.assertEqual(pathlib.Path(env['TEMP']).parent,self.root/'data')

    def test_tools_are_allowlisted_and_unmanaged_editors_are_not_used(self):
        for name in ['exec','script.eval','script_eval','script.eval_file','desktop.capture','environment.info']:
            self.assertTrue(DENIED.search(name));
            with self.assertRaises(ValueError):self.control.call('approved',name)
        with self.assertRaisesRegex(ValueError,'unity_start'):self.control.tools('approved')

    def test_mcp_tools_filter_and_call_without_shell(self):
        script=self.root/'fake.py';script.write_text('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m:continue
 r={'tools':[{'name':n,'inputSchema':{'type':'object'}} for n in ['scene_info','exec','script.eval','desktop.capture','batch','invoke_menu','run','run']]} if m['method']=='tools/list' else {'content':[{'type':'text','text':'ok'}]} if m['method']=='tools/call' else {}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
''')
        real_popen=subprocess.Popen
        def spawn(args,**kwargs):
            self.assertIn('--project-path',args);self.assertNotIn('shell',kwargs)
            kwargs.pop('creationflags',None)
            return real_popen([sys.executable,str(script)],**kwargs)
        self.control.start('approved')
        with patch('native_unity.subprocess.Popen',side_effect=spawn):
            names=[t['name'] for t in self.control.tools('approved')['tools']]
            self.assertIn('scene_info',names);self.assertIn('console.get',names)
            self.assertNotIn('run',names);self.assertNotIn('batch',names)
            self.assertFalse(self.control.call('approved','scene_info').get('isError',False))
            with self.assertRaises(ValueError):self.control.call('approved','unknown')
            with self.assertRaises(ValueError):self.control.call('approved','run')
            with self.assertRaises(ValueError):self.control.call('approved','batch')


if __name__=='__main__':unittest.main()
