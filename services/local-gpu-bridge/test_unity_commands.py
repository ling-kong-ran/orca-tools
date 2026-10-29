import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch
from native_unity_commands import invoke, BY_NAME


class QualifiedUnityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.control=types.SimpleNamespace(project=lambda _:({},self.root),
            settings=lambda:{'unity_cli_executable':'dedicated-cli.exe'},environment=lambda:{'TZ':'UTC'})

    def run_command(self,name,args,result=None,code=0):
        with patch('native_unity_commands.subprocess.run',return_value=types.SimpleNamespace(
                returncode=code,stdout=json.dumps(result or {'ok':True}))) as run:
            reply=invoke(self.control,'approved',name,args)
            return reply,run.call_args

    def test_qualified_routing_and_async_test_arguments(self):
        reply,call=self.run_command('test.run',{'filter':'--exec $(test)'})
        args=call.args[0]
        self.assertEqual(args[:4],['dedicated-cli.exe','command','test','run'])
        self.assertIn('--filter=--exec $(test)',args)
        self.assertIn('--async_tests=true',args)
        self.assertNotIn('shell',call.kwargs)
        self.assertEqual(call.kwargs['cwd'],self.root)

    def test_output_and_scene_paths_are_project_scoped(self):
        for path in ['../oops.exe','C:/oops.exe','Assets/Source.cs','Builds/../oops.exe','Builds/oops/../../a.exe']:
            with self.assertRaises(ValueError):self.run_command('build.run',{'outputPath':path})
        with self.assertRaises(ValueError):self.run_command('build.run',{'scenes':['../Other.unity']})
        _,call=self.run_command('build.run',{'dry_run':True})
        self.assertIn('--outputPath=Builds/Game.exe',call.args[0])

    def test_errors_preserved_but_host_data_filtered(self):
        reply,_=self.run_command('console.get',{'tail':5},{'entries':[{'message':'compile failed at C:\\private\\file.cs',
            'account':{'email':'hidden'},'public_ip':'123.1.2.3'}]},1)
        self.assertTrue(reply['isError']);text=reply['content'][0]['text']
        self.assertIn('compile failed',text);self.assertNotIn('C:',text)
        self.assertNotIn('123.1.2.3',text)

    def test_arguments_and_registry_packages_are_restricted(self):
        for name,args in [('console.get',{'tail':201}),('test.run',{'mode':'invalid'}),
                ('build.run',{'confirm':'yes'}),('console.get',{'project-path':'other'}),
                ('package.add',{'identifier':'file:../secret'}),('package.add',{'identifier':'https://example.com/pkg.git'})]:
            with self.assertRaises(ValueError):self.run_command(name,args)
        _,call=self.run_command('package.add',{'identifier':'com.unity.entities@1.5.0','dry_run':True})
        self.assertIn('--wait=false',call.args[0])
        self.assertIn('build.run',BY_NAME)


if __name__=='__main__':unittest.main()
