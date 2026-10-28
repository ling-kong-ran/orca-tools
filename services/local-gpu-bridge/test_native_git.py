import json,pathlib,subprocess,tempfile,types,unittest,time,uuid
from unittest.mock import patch
from native_git import ProjectGit
from native_control import NativeControl

class GitTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.remote=self.root/'remote.git';self.source=self.root/'source';self.mirror=self.root/'mirror'
  self.cmd(['init','--bare','--initial-branch=main',str(self.remote)])
  self.cmd(['init','--initial-branch=main',str(self.source)])
  self.cmd(['config','user.name','Fixture'],self.source);self.cmd(['config','user.email','fixture@example.invalid'],self.source)
  (self.source/'scene.txt').write_text('remote one');(self.source/'.gitignore').write_text('reserved.json\n')
  self.cmd(['add','.'],self.source);self.cmd(['commit','-m','initial'],self.source);self.cmd(['remote','add','origin',str(self.remote)],self.source);self.cmd(['push','origin','main'],self.source)
  self.cmd(['clone',str(self.remote),str(self.mirror)])
  self.data=self.root/'bridge/native';self.data.mkdir(parents=True)
  self.project={'id':'fixture','root':str(self.mirror),'enabled':True,'git':{'enabled':True,'remote':'origin','branch':'main','auto_pull_before_render':True}}
  self.control=types.SimpleNamespace(root=self.data,config={'native':{'git_executable':'git'}})
 def tearDown(self):self.tmp.cleanup()
 def cmd(self,args,cwd=None):return subprocess.run(['git',*args],cwd=cwd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
 def test_git_update_discards_local_edits_without_creating_backups(self):
  (self.mirror/'scene.txt').write_text('local discarded');(self.mirror/'new.txt').write_text('local collision');(self.mirror/'reserved.json').write_text('ignored local collision');(self.mirror/'render.blend').write_bytes(b'keep generated result')
  (self.source/'scene.txt').write_text('remote two');(self.source/'new.txt').write_text('remote new');(self.source/'reserved.json').write_text('remote reserved')
  self.cmd(['add','scene.txt','new.txt'],self.source);self.cmd(['add','-f','reserved.json'],self.source);self.cmd(['commit','-m','latest'],self.source);self.cmd(['push','origin','main'],self.source)
  git=ProjectGit(self.control,self.project,self.mirror);previous=git.status()['head'];result=git.pull()
  self.assertEqual((self.mirror/'scene.txt').read_text(),'remote two');self.assertEqual((self.mirror/'new.txt').read_text(),'remote new');self.assertEqual((self.mirror/'reserved.json').read_text(),'remote reserved')
  self.assertEqual((self.mirror/'render.blend').read_bytes(),b'keep generated result');self.assertEqual(git.status()['tracked_changes'],0)
  self.assertFalse(result['backup_created']);self.assertNotIn('backup_id',result)
  self.assertFalse((self.data/'git-backups').exists())
  self.assertEqual(self.cmd(['for-each-ref','--format=%(refname)','refs/local-gpu-backups/'],self.mirror),b'')
  self.assertFalse(git.pull()['updated'])
 def test_root_and_git_arguments_are_scoped(self):
  sub=self.mirror/'child';sub.mkdir()
  with self.assertRaisesRegex(ValueError,'approved project root'):ProjectGit(self.control,self.project,sub)
  for branch in ('--upload-pack=evil','../other','main:other','main~2'):
   with self.assertRaises(ValueError):ProjectGit(self.control,{**self.project,'git':{**self.project['git'],'branch':branch}},self.mirror)
  git=ProjectGit(self.control,self.project,self.mirror)
  for name in ('../outside','.git/config','C:/outside','folder/../a'):
   with self.assertRaises(ValueError):git.file(name)
 def test_transient_windows_file_lock_is_retried_without_backup(self):
  (self.mirror/'scene.txt').write_text('local render edit')
  original=subprocess.run;attempts=[]
  def temporary_lock(command,**kwargs):
   if 'reset' in command:
    attempts.append(command)
    if len(attempts)==1:return subprocess.CompletedProcess(command,1,stdout=b'',stderr=b'error: unable to unlink old scene.txt: Invalid argument')
   return original(command,**kwargs)
  with patch('native_git.subprocess.run',side_effect=temporary_lock),patch('native_git.time.sleep'):
   result=ProjectGit(self.control,self.project,self.mirror).pull()
  self.assertEqual(len(attempts),2);self.assertTrue(result['updated']);self.assertEqual((self.mirror/'scene.txt').read_text(),'remote one')
 def test_only_git_is_exposed_for_sync(self):
  from importlib.util import spec_from_file_location,module_from_spec
  spec=spec_from_file_location('test_git_client',pathlib.Path(__file__).parent/'plugin/client.py');m=module_from_spec(spec);spec.loader.exec_module(m)
  names={t['name'] for t in m.GODOT_TOOLS};self.assertIn('project_git',names);self.assertFalse(names&{'sync_project','upload_project_file','apply_project_sync'})
  config={'data_dir':str(self.root/'service'),'native':{'git_only_sync':True,'projects':[dict(self.project,name='Fixture',godot_subdir='client')]}}
  control=NativeControl(config)
  with self.assertRaisesRegex(ValueError,'uses Git'):control.sync_plan({'project_id':'fixture','files':[]})
  with self.assertRaisesRegex(ValueError,'uses Git'):control.upload_chunk({})
  with self.assertRaisesRegex(ValueError,'uses Git'):control.apply_sync('missing')
 def test_render_pulls_remote_before_opening_scene(self):
  client=self.source/'client';client.mkdir();(client/'main.tscn').write_text('[gd_scene]\n[node name="Fixture" type="Node"]\n')
  (self.source/'scene.txt').write_text('latest before render');self.cmd(['add','scene.txt','client/main.tscn'],self.source);self.cmd(['commit','-m','render update'],self.source);self.cmd(['push','origin','main'],self.source)
  project=dict(self.project,name='Fixture',godot_subdir='client')
  class Ready:
   def ready(self,engine):return True
   def require(self,engine):pass
  control=NativeControl({'data_dir':str(self.root/'render-service'),'native':{'projects':[project]}},guard=Ready())
  def capture(job,*args):
   self.assertEqual((self.mirror/'scene.txt').read_text(),'latest before render');self.assertTrue((self.mirror/'client/main.tscn').is_file());job['result']={'captured':True}
  control.run_godot=capture
  job=control.queue({'project_id':'fixture','engine':'godot','operation':'capture','arguments':{'scene':'main.tscn'},'request_id':uuid.uuid4().hex})
  deadline=time.monotonic()+20
  while control.jobs[job['id']]['status'] in ('queued','running') and time.monotonic()<deadline:time.sleep(.05)
  result=control.job_status(job['id']);self.assertEqual(result['status'],'succeeded');self.assertTrue(result['result']['git_update']['updated'])
 def test_git_failure_is_distinct_and_does_not_run_blender_code(self):
  project=dict(self.project,name='Fixture',allow_scripts=True)
  class Ready:
   def ready(self,engine):return True
   def require(self,engine):pass
  control=NativeControl({'data_dir':str(self.root/'failed-service'),'native':{'projects':[project]}},guard=Ready())
  job={'id':uuid.uuid4().hex,'project_id':'fixture','engine':'blender','operation':'execute_code',
       'arguments':{'code':'result=1'},'status':'queued','artifacts':[]}
  control.jobs[job['id']]=job
  with patch('native_git.ProjectGit.pull',side_effect=ValueError('private host detail')),patch.object(control,'run_blender') as blender:
   with self.assertLogs(level='ERROR'):control.run(job)
   blender.assert_not_called()
  result=control.job_status(job['id'])
  self.assertEqual(result['error_stage'],'git_sync');self.assertIn('before the native operation',result['error'])
  self.assertNotIn('private host',json.dumps(result))

if __name__=='__main__':unittest.main(verbosity=2)
