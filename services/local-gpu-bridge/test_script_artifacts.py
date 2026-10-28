import json,os,pathlib,tempfile,types,unittest,uuid
from unittest.mock import patch
from native_script import run_script
from native_control import NativeControl


class ScriptArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);self.project=self.root/'project';self.project.mkdir()
        (self.project/'tools').mkdir();(self.project/'tools/shots.gd').write_text('extends SceneTree\n',encoding='utf-8')
        self.output=self.project/'docs/shots';self.output.mkdir(parents=True)
        self.control=types.SimpleNamespace(root=self.root/'native',config={'native':{'godot_executable':'godot.exe'}})
        self.artifacts=self.root/'artifacts';self.artifacts.mkdir()
        self.job={'id':uuid.uuid4().hex,'project_id':'test','arguments':{'script':'tools/shots.gd','timeout_seconds':10}}

    def factory(self,code=1,write=True):
        def create(args,cwd,log,env):
            pathlib.Path(log).write_text('ok raid/hud\nFAIL raid/extract: timed out\n',encoding='utf-8')
            if write:(self.output/'good.png').write_bytes(b'identical screenshot')
            return types.SimpleNamespace(poll=lambda:code,close=lambda:None,stop=lambda:None)
        return create

    def test_failed_batch_keeps_successful_images_and_names_the_failed_shot(self):
        self.control.process_factory=self.factory()
        run_script(self.control,self.job,{'allow_scripts':True},self.project,self.artifacts)
        self.assertTrue(self.job['result']['partial_success']);self.assertFalse(self.job['result']['script_completed'])
        self.assertEqual(self.job['result']['failed_screenshots'],['raid/extract'])
        self.assertEqual(len(self.job['artifacts']),1)
        self.assertEqual((self.artifacts/self.job['artifacts'][0]['file']).read_bytes(),b'identical screenshot')

    def test_repeated_identical_picture_is_collected_when_script_rewrites_it(self):
        file=self.output/'good.png';file.write_bytes(b'identical screenshot');os.utime(file,(1,1))
        self.control.process_factory=self.factory(code=0)
        run_script(self.control,self.job,{'allow_scripts':True},self.project,self.artifacts)
        self.assertTrue(self.job['result']['script_completed']);self.assertEqual(len(self.job['artifacts']),1)

    def test_no_picture_failure_still_raises(self):
        self.control.process_factory=self.factory(write=False)
        with self.assertRaisesRegex(ValueError,'script failed'):
            run_script(self.control,self.job,{'allow_scripts':True},self.project,self.artifacts)

    def test_partial_failure_status_allows_only_that_jobs_registered_artifacts(self):
        control=NativeControl({'data_dir':str(self.root/'service'),'native':{'projects':[
            {'id':'test','enabled':True,'root':str(self.project),'allow_scripts':True}]}})
        job={**self.job,'engine':'godot','operation':'script','status':'running','artifacts':[]}
        control.jobs[job['id']]=job
        directory=control.root/'artifacts';directory.mkdir()
        file=directory/(job['id']+'-0.png');file.write_bytes(b'png')
        def partial(*args):
            job['result']={'partial_success':True,'script_completed':False,'artifact_count':1,'failed_screenshots':['raid/extract']}
            job['artifacts']=[{'index':0,'filename':'docs/shots/good.png','file':file.name}]
        with patch.object(control.guard,'require'),patch.object(control,'import_godot'),patch('native_script.run_script',side_effect=partial):
            control.run(job)
        public=control.job_status(job['id'])
        self.assertEqual(public['status'],'failed');self.assertEqual(public['error_stage'],'script')
        self.assertEqual(control.artifact(job['id'],0),file)
        with self.assertRaises(ValueError):control.artifact(job['id'],1)

    def test_remote_client_downloads_partial_native_result_but_rejects_other_failed_jobs(self):
        import importlib.util,io,hashlib
        from unittest.mock import Mock
        spec=importlib.util.spec_from_file_location('partial_artifact_client',pathlib.Path(__file__).parent/'plugin/client.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        client=module.Client.__new__(module.Client)
        data=b'completed screenshot';response=io.BytesIO(data);response.headers={'Content-Length':str(len(data))}
        job={'status':'failed','result':{'partial_success':True},'artifacts':[{'index':0,'filename':'good.png'}]}
        client.request=Mock(side_effect=[job,response])
        args={'job_id':self.job['id'],'index':0,'destination_dir':str(self.root/'downloads')}
        receipt=client.call('fetch_native_artifact',args)
        self.assertEqual(pathlib.Path(receipt['path']).read_bytes(),data)
        self.assertEqual(receipt['sha256'],hashlib.sha256(data).hexdigest())
        for tool in ('fetch_artifact','fetch_native_artifact'):
            client.request=Mock(return_value={**job,'result':{}})
            with self.assertRaisesRegex(ValueError,'not ready'):client.call(tool,args)
            self.assertEqual(client.request.call_count,1)


if __name__=='__main__':unittest.main()
