import base64,hashlib,json,pathlib,tempfile,unittest,uuid,threading,subprocess,sys,time,os
from unittest.mock import patch
from native_control import NativeControl,inside,private_result
from native_process import ManagedProcess

class Denied:
 def ready(self,engine):return False
 def require(self,engine):raise ValueError('Native network isolation is not ready.')
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.project=self.root/'project';self.project.mkdir()
  self.config={'data_dir':str(self.root/'bridge'),'native':{'projects':[{'id':'test','name':'Test','root':str(self.project),'godot_subdir':'client','enabled':True}]}}
  self.control=NativeControl(self.config,guard=Denied())
 def tearDown(self):self.temp.cleanup()
 def plan(self,path,data):
  return self.control.sync_plan({'project_id':'test','files':[{'path':path,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]})
 def upload(self,data,offset=0,sha=None,total=None):
  return self.control.upload_chunk({'sha256':sha or hashlib.sha256(data).hexdigest(),'bytes':len(data) if total is None else total,'offset':offset,'data':base64.b64encode(data).decode()})
 def test_paths_credentials_executables_and_reparse_denied(self):
  for name in ('../a','/a','C:/a','x\\a','.git/config','.env.production','a/.ssh/config','tools/x.ps1','client/evil.dll','client/con.png','folder/a:stream','server/saves/user.json'):
   with self.subTest(name=name),self.assertRaises(ValueError):self.plan(name,b'x')
  external=self.root/'private';external.mkdir()
  try:(self.project/'link').symlink_to(external,target_is_directory=True)
  except OSError:return
  with self.assertRaises(ValueError):inside(self.project,'link/a.txt')
 def test_incremental_sync_conflicts_and_backup(self):
  data=b'first version';plan=self.plan('client/scripts/a.gd',data);self.assertEqual(plan['files'][0]['status'],'add');self.upload(data)
  result=self.control.apply_sync(plan['id']);self.assertEqual(result['status'],'applied');file=self.project/'client/scripts/a.gd';self.assertEqual(file.read_bytes(),data)
  self.assertEqual(self.control.apply_sync(plan['id'])['status'],'applied')
  self.assertEqual(self.plan('client/scripts/a.gd',data)['files'][0]['status'],'same')
  next_data=b'remote second';next_plan=self.plan('client/scripts/a.gd',next_data);self.assertEqual(next_plan['files'][0]['status'],'update')
  file.write_bytes(b'local edit');self.upload(next_data)
  with self.assertRaisesRegex(ValueError,'changed after preview'):self.control.apply_sync(next_plan['id'])
  conflict=self.plan('client/scripts/a.gd',next_data);self.assertEqual(conflict['files'][0]['status'],'conflict')
  with self.assertRaisesRegex(ValueError,'Local files differ'):self.control.apply_sync(conflict['id'])
  self.control.apply_sync(conflict['id'],approve_conflicts=True);self.assertEqual(file.read_bytes(),next_data)
  self.assertEqual((self.control.root/'backups'/conflict['id']/'client/scripts/a.gd').read_bytes(),b'local edit')
 def test_upload_requires_plan_hash_validation_and_resume(self):
  data=b'abcdef';sha=hashlib.sha256(data).hexdigest()
  with self.assertRaises(ValueError):self.upload(data)
  self.plan('a.png',data)
  one=self.upload(b'abc',sha=sha,total=6);self.assertEqual(one,{'offset':3,'complete':False})
  wrong=self.upload(b'abc',sha=sha,total=6);self.assertEqual(wrong['offset'],3)
  self.assertTrue(self.upload(b'def',offset=3,sha=sha,total=6)['complete'])
  bad=self.plan('other.png',b'original')
  with self.assertRaisesRegex(ValueError,'hash mismatch'):self.upload(b'tampered',sha=bad['files'][0]['sha256'],total=8)
 def test_remote_wins_overwrites_conflicts_and_backs_up_latest_content(self):
  file=self.project/'scene.tscn';file.write_bytes(b'local original')
  plan=self.plan('scene.tscn',b'remote authoritative');self.upload(b'remote authoritative')
  self.assertEqual(plan['files'][0]['status'],'conflict')
  # A policy change also applies to a preview made before that change.
  project=self.config['native']['projects'][0];project['sync_policy']='remote_wins'
  self.assertEqual(self.control.public_plan(self.control.plans[plan['id']])['sync_policy'],'remote_wins')
  file.write_bytes(b'latest local output')
  result=self.control.apply_sync(plan['id'])
  self.assertEqual(result['status'],'applied');self.assertFalse(result['conflicts_approved'])
  self.assertEqual(file.read_bytes(),b'remote authoritative')
  self.assertEqual((self.control.root/'backups'/plan['id']/'scene.tscn').read_bytes(),b'latest local output')
  same=self.plan('scene.tscn',file.read_bytes());file.write_bytes(b'changed after unchanged preview')
  with self.assertRaisesRegex(ValueError,'Create a new sync plan'):self.control.apply_sync(same['id'])
 def test_project_policy_validation_and_preservation(self):
  project=self.config['native']['projects'][0]
  self.control.manage_project({**project,'sync_policy':'remote_wins'})
  self.assertEqual(self.control.projects()[0]['sync_policy'],'remote_wins')
  self.control.manage_project({**project,'enabled':False})
  self.assertEqual(self.control.projects()[0]['sync_policy'],'remote_wins')
  with self.assertRaisesRegex(ValueError,'Invalid sync policy'):self.control.manage_project({**project,'sync_policy':'unknown'})
  self.assertEqual(self.control.projects()[0]['sync_policy'],'remote_wins')
 def test_empty_file_and_duplicate_case_destinations(self):
  plan=self.plan('empty.txt',b'');self.assertTrue(self.upload(b'')['complete']);self.control.apply_sync(plan['id']);self.assertEqual((self.project/'empty.txt').stat().st_size,0)
  item={'path':'A.gd','bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}
  with self.assertRaises(ValueError):self.control.sync_plan({'project_id':'test','files':[item,{**item,'path':'a.gd'}]})
 def test_unexposed_commands_and_privacy_fail_closed(self):
  for op in ('shell','execute','python'):
   with self.assertRaisesRegex(ValueError,'not exposed'):self.control.queue({'project_id':'test','engine':'blender','operation':op,'arguments':{},'request_id':uuid.uuid4().hex})
  with self.assertRaisesRegex(ValueError,'isolation'):self.control.queue({'project_id':'test','engine':'blender','operation':'scene_info','request_id':uuid.uuid4().hex})
  self.assertEqual(len(self.control.jobs),0)
  self.assertNotIn(str(self.project),json.dumps(self.control.status()))
 def test_project_script_permissions_arguments_and_broker(self):
  from native_script import script_request,adapt_script,ProcessBroker
  project=self.config['native']['projects'][0];(self.project/'test.gd').write_text('extends SceneTree\n')
  body={'project_id':'test','engine':'blender','operation':'execute_code','arguments':{'code':'result=123'},'request_id':uuid.uuid4().hex}
  with self.assertRaisesRegex(ValueError,'script access is disabled'):self.control.queue(body)
  project['allow_scripts']=True
  with self.assertRaisesRegex(ValueError,'isolation'):self.control.queue(body)
  args={'script':'test.gd','user_args':['--outfits=coat','--view=front']}
  self.assertEqual(script_request(self.control,project,self.project,'script',args).name,'test.gd')
  with self.assertRaises(ValueError):script_request(self.control,project,self.project,'script',{**args,'script':'../test.gd'})
  with self.assertRaises(ValueError):script_request(self.control,project,self.project,'script',{**args,'user_args':'--outfits=x'})
  with self.assertRaises(ValueError):script_request(self.control,project,self.project,'script',{**args,'output_paths':['../private']})
  self.control.validate_blender('execute_code',{'code':'import bpy;result=123'},self.project)
  self.config['native']['godot_executable']=str(self.root/'godot.exe')
  broker=ProcessBroker(self.control,{'project_id':'test'},self.project,self.root)
  with self.assertRaisesRegex(ValueError,'not exposed'):broker.execute('powershell.exe',[])
  with self.assertRaisesRegex(ValueError,'Only the project'):broker.execute('go',['run','evil.go'])
  adapted=adapt_script('extends SceneTree\nfunc _initialize():\n\tOS.create_process("cmd", [])\n')
  self.assertIn('_bridge_create("cmd", [])',adapted);self.assertNotIn('OS.create_process(',adapted)
 def test_project_revocation_and_file_filtering(self):
  (self.project/'.env').write_text('secret');(self.project/'scene.tscn').write_text('[gd_scene]')
  self.assertEqual([f['path'] for f in self.control.files('test')['files']],['scene.tscn'])
  self.config['native']['projects'][0]['enabled']=False
  with self.assertRaises(ValueError):self.control.files('test')
 def test_raw_metadata_redacted(self):
  value=private_result({'device':'secret GPU','hostname':'machine','objects':[{'name':'address 8.8.8.8'}],'error':'failed at C:\\Users\\person\\secret.txt'})
  encoded=json.dumps(value);self.assertNotIn('secret GPU',encoded);self.assertNotIn('machine',encoded);self.assertNotIn('8.8.8.8',encoded);self.assertNotIn('person',encoded)
 def test_text_downloads_filter_metadata_without_changing_local_source(self):
  file=self.project/'shots.json'
  original={'device':'NVIDIA GeForce RTX 5090','hostname':'private-pc','network':{'ip':'8.8.8.8'},'picture':'portrait','note':'endpoint 2001:db8::42 and 8.8.4.4 mac aa:bb:cc:dd:ee:ff'}
  file.write_text(json.dumps(original))
  read=self.control.read_file('test','shots.json')['text']
  downloaded=self.control.project_download('test','shots.json').read_text()
  for value in [read,downloaded]:
   for secret in ['NVIDIA','private-pc','8.8.8.8','2001:db8::42','8.8.4.4','aa:bb:cc:dd:ee:ff']:self.assertNotIn(secret,value)
   self.assertIn('portrait',value)
  self.assertEqual(json.loads(file.read_text()),original)
 def test_automatic_privacy_setup_checks_then_requests_windows_elevation(self):
  self.config['native']['godot_executable']='C:/fixture/Godot-LocalGpu.exe'
  class Guard:
   installed=False
   def ready(self,engine):return self.installed
  guard=Guard();self.control.guard=guard
  def install(*args,**kwargs):
   self.assertIn('RunAs',args[0][-1]);self.assertIn('Setup-Native-Privacy.ps1',args[0][-1]);guard.installed=True
   return subprocess.CompletedProcess(args[0],0)
  with patch('native_control.subprocess.run',side_effect=install) as run:
   self.control.setup_privacy()
   deadline=time.monotonic()+3
   while self.control.privacy_setup['status'] in ('checking','awaiting_permission') and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(self.control.privacy_setup['status'],'ready');self.assertEqual(run.call_count,1)
   self.control.setup_privacy()
   deadline=time.monotonic()+3
   while self.control.privacy_setup['status']=='checking' and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(run.call_count,1)
 def test_automatic_privacy_setup_does_not_mark_cancelled_setup_ready(self):
  self.config['native']['godot_executable']='C:/fixture/Godot-LocalGpu.exe'
  with patch('native_control.subprocess.run',return_value=subprocess.CompletedProcess([],1)):
   self.control.setup_privacy()
   deadline=time.monotonic()+3
   while self.control.privacy_setup['status'] in ('checking','awaiting_permission') and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(self.control.privacy_setup['status'],'failed');self.assertFalse(self.control.guard.ready('godot'))
 def test_comfy_only_setup_does_not_request_renderer_firewall(self):
  with patch('native_control.subprocess.run') as run:
   self.control.setup_privacy()
   deadline=time.monotonic()+3
   while self.control.privacy_setup['status']=='checking' and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(self.control.privacy_setup['status'],'ready');run.assert_not_called()
 def test_windows_child_process_denied(self):
  if os.name!='nt':self.skipTest('Windows only')
  marker=self.root/'blocked.txt';script=self.root/'probe.py'
  script.write_text('import subprocess,sys,pathlib\ntry:\n subprocess.run([sys.executable,"-c","pass"],check=True)\nexcept OSError:\n pathlib.Path(sys.argv[1]).write_text("child denied")\nelse:\n raise SystemExit(7)\n')
  process=ManagedProcess([sys.executable,str(script),str(marker)],self.root,self.root/'app.log')
  try:self.assertEqual(process.wait(15),0);self.assertEqual(marker.read_text(),'child denied')
  finally:process.close()
 def test_firewall_blocks_complement_of_loopback_tailnet_and_all_ipv6(self):
  import ipaddress,re
  from native_process import BLOCKED_ADDRESSES
  script=(pathlib.Path(__file__).parent/'Setup-Native-Privacy.ps1').read_text()
  declaration=re.search(r'\$nativeBlocked = @\(([^\n]+)\)',script)[1]
  self.assertEqual(set(re.findall(r"'([^']+)'",declaration)),BLOCKED_ADDRESSES)
  networks=[ipaddress.ip_network(s) for s in BLOCKED_ADDRESSES]
  v4=[n for n in networks if n.version==4];v6=[n for n in networks if n.version==6]
  allowed=[ipaddress.ip_network(s) for s in ('127.0.0.0/8','100.64.0.0/10')]
  self.assertFalse(any(a.overlaps(b) for a in allowed for b in v4))
  self.assertEqual(list(ipaddress.collapse_addresses(v4+allowed)),[ipaddress.ip_network('0.0.0.0/0')])
  self.assertEqual(list(ipaddress.collapse_addresses(v6)),[ipaddress.ip_network('::/0')])
 def test_standard_user_firewall_check_normalizes_windows_subnet_masks(self):
  import ipaddress
  from native_process import EgressGuard,BLOCKED_ADDRESSES
  exe=self.root/'managed.exe';exe.write_bytes(b'fixture')
  guard=EgressGuard({'godot_executable':str(exe)})
  addresses=[str(ipaddress.ip_network(s).with_netmask) if ':' not in s else s for s in BLOCKED_ADDRESSES]
  value={'program':str(exe),'remote':addresses}
  with patch('native_process.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout=json.dumps(value))) as run:
   self.assertTrue(guard.ready('godot'));self.assertIn('HNetCfg.FwPolicy2',run.call_args[0][0][-1])
  value['remote'].pop()
  with patch('native_process.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout=json.dumps(value))):self.assertFalse(guard.ready('godot'))

if __name__=='__main__':unittest.main(verbosity=2)
