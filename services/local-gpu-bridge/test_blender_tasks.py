import ast,contextlib,json,os,pathlib,shutil,sys,tempfile,types,unittest,uuid
from unittest.mock import patch
from native_blender_output import Capture,result,diagnostic
from native_control import NativeControl,private_result

class Guard:
    def require(self,engine):pass
    def ready(self,engine):return True

class BlenderTasks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);self.spool=self.root/'spool';self.spool.mkdir();self.out=self.root/'out';self.out.mkdir()
        self.config={'data_dir':str(self.root/'bridge'),'native':{'projects':[{'id':'test','name':'Test','root':str(self.root),'enabled':True,'allow_scripts':True}]}}
        self.control=NativeControl(self.config,guard=Guard())
        source=ast.parse(pathlib.Path(__file__).with_name('native_blender.py').read_text(encoding='utf-8'))
        functions=ast.Module(body=[node for node in source.body if isinstance(node,ast.FunctionDef) and node.name in ('execute','local_file','vec')],type_ignores=[])
        self.scope=dict(bpy=types.SimpleNamespace(),json=json,pathlib=pathlib,sys=sys,os=os,contextlib=contextlib,shutil=shutil,root=self.root,spool=self.spool,out=self.out,Capture=Capture,safe_result=result,diagnostic=diagnostic)
        exec(compile(functions,'native_blender.py','exec'),self.scope)
    def execute(self,operation,args):return self.scope['execute'](operation,args,'a'*32)
    def test_script_results_messages_failure_and_artifacts(self):
        value=self.execute('execute_code',{'code':"print('hello');result={'count':3,'email':'private@example.com','note':'private@example.com 8.8.8.8'}; (project_root/'model.json').write_text('{}')",'output_paths':['model.json']})
        cleaned=private_result(result(value));encoded=json.dumps(cleaned)
        self.assertEqual(cleaned['result']['count'],3);self.assertIn('hello',cleaned['messages']);self.assertNotIn('private@example.com',encoded);self.assertNotIn('8.8.8.8',encoded)
        self.assertEqual(len(value['artifacts']),1);self.assertTrue((self.out/value['artifacts'][0]).exists())
        failure=self.execute('execute_code',{'code':"print('before');raise ValueError('test private@example.com 1.2.3.4')"})
        self.assertFalse(failure['executed']);self.assertEqual(failure['diagnostic']['type'],'ValueError');self.assertIn('before',failure['messages'])
        syntax=self.execute('execute_code',{'code':'if !!!'})
        self.assertEqual(syntax['diagnostic']['type'],'SyntaxError');self.assertEqual(syntax['diagnostic']['line'],1)
    def test_bounded_output(self):
        c=Capture();c.write('x'*100000);self.assertEqual(len(c.text),8192);self.assertTrue(c.truncated)
        self.assertTrue(result({str(i):'x'*8192 for i in range(100)})['truncated'])
        self.assertLess(len(json.dumps(result([[[[[[[[[['x']]]]]]]]]]))),200)
    def test_batch_failure_policy_and_progress(self):
        steps=[{'operation':'execute_code','arguments':{'code':code}} for code in ('result=1',"raise ValueError('test')",'result=3')]
        value=self.execute('batch',{'steps':steps});self.assertEqual(value['completed'],2);self.assertTrue(value['partial_success'])
        value=self.execute('batch',{'steps':steps,'continue_on_error':True});self.assertEqual(value['completed'],3);self.assertEqual(value['steps'][2]['status'],'succeeded')
        self.assertEqual(json.loads((self.spool/('a'*32+'.progress.json')).read_text())['completed'],2)
    def test_batch_validation_and_script_permission(self):
        for args in ({'steps':[]},{'steps':[{'operation':'batch','arguments':{}}]},{'steps':[{'operation':'execute_code','arguments':{'code':'x','output_paths':['../secret.json']}}]}):
            with self.assertRaises(ValueError):self.control.validate_blender('batch',args,self.root)
        self.config['native']['projects'][0]['allow_scripts']=False
        with self.assertRaisesRegex(ValueError,'script access is disabled'):self.control.queue({'project_id':'test','engine':'blender','operation':'batch','arguments':{'steps':[{'operation':'execute_code','arguments':{'code':'result=1'}}]},'request_id':uuid.uuid4().hex})
    def test_queued_cancellation_and_listing(self):
        job={'id':'a'*32,'project_id':'test','engine':'blender','operation':'scene_info','arguments':{},'status':'queued','created_at':1,'artifacts':[]}
        self.control.jobs[job['id']]=job
        self.assertEqual(len(self.control.blender_tasks('test')['jobs']),1)
        self.assertEqual(self.control.cancel_blender(job['id'])['status'],'cancelled')
        with patch.object(self.control,'run_blender') as run:self.control.run(job);run.assert_not_called()
        job['engine']='godot'
        with self.assertRaises(ValueError):self.control.cancel_blender(job['id'])

if __name__=='__main__':unittest.main()
