import base64, copy, hashlib, importlib.util, io, json, pathlib, socket, subprocess, sys, tempfile, threading, unittest, unittest.mock, urllib.error, urllib.request, uuid
from datetime import datetime, timezone, timedelta
from bridge import Bridge, Server, make_handler, apply_parameters, validate_workflow
spec=importlib.util.spec_from_file_location('mcp_client',pathlib.Path(__file__).parent/'plugin/client.py')
client_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(client_module)

class FakeResponse(io.BytesIO):
    def __init__(self,value):super().__init__(value);self.headers={'Content-Length':str(len(value))}

class FakeAdapter:
    def __init__(self):self.submissions=0;self.states={};self.bytes=b'example generated artifact';self.cancelled=[]
    def status(self):return {'online':True,'devices':[{'name':'test GPU'}],'running':0,'pending':0}
    def submit(self,prompt,client_id):
        self.submissions+=1;ident=str(uuid.uuid4());self.states[ident]={'status':'queued'};return ident
    def inspect(self,prompt_id):return self.states[prompt_id]
    def complete(self,prompt_id):self.states[prompt_id]={'status':'succeeded','artifacts':[{'filename':'result.png','subfolder':'own','type':'output'}]}
    def cancel_pending(self,prompt_id):self.cancelled.append(prompt_id);self.states[prompt_id]={'status':'unknown'};return True
    def artifact(self,item):return FakeResponse(self.bytes)
    def upload(self,name,content):return {'reference':'local-gpu-bridge/'+name,'bytes':len(content)}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);(self.root/'workflows').mkdir()
        self.workflow=json.loads((pathlib.Path(__file__).parent/'example-workflow.json').read_text())
        (self.root/'workflows/connection-test.json').write_text(json.dumps(self.workflow))
        self.config={'data_dir':str(self.root),'token':'a'*64,'allowed_peers':['127.0.0.1'],'listen':'127.0.0.1','max_active_jobs':8}
        self.adapter=FakeAdapter();self.bridge=Bridge(self.config,self.adapter)
        self.server=Server(('127.0.0.1',0),make_handler(self.bridge));threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.client_config=self.root/'client.json';self.client_config.write_text(json.dumps({'url':self.url,'token':self.config['token']}))
        self.client=client_module.Client(self.client_config)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.temp.cleanup()
    def submit(self):return self.client.call('run_workflow',{'workflow_id':'connection-test','parameters':{'color':123},'request_id':'b'*32})
    def test_blender_task_tools_use_authenticated_routes_and_filter_results(self):
        with unittest.mock.patch.object(self.bridge.native,'blender_tasks',return_value={'jobs':[{'message':'test@example.com 8.8.8.8'}]}) as listed:
            value=self.client.call('blender_tasks',{'project_id':'test'})
            listed.assert_called_once_with(project_id='test')
            self.assertNotIn('test@example.com',json.dumps(value));self.assertNotIn('8.8.8.8',json.dumps(value))
        with unittest.mock.patch.object(self.bridge.native,'cancel_blender',return_value={'status':'cancelled'}) as cancelled:
            self.assertEqual(self.client.call('cancel_blender_task',{'job_id':'a'*32})['status'],'cancelled')
            cancelled.assert_called_once_with(ident='a'*32)
        with self.assertRaises(ValueError):self.client.call('cancel_blender_task',{'job_id':'../x'})
        definition=next(t for t in client_module.BLENDER_TOOLS if t['name']=='blender_operation')
        self.assertIn('batch',definition['inputSchema']['properties']['operation']['enum'])
        self.assertIn('viewport_capture',definition['inputSchema']['properties']['operation']['enum'])
    def test_remote_boundary_filters_tripo_status_and_errors(self):
        with unittest.mock.patch.object(self.bridge.tripo, 'status', return_value={
            'connected': True, 'region': 'cn', 'timezone': 'Asia/Shanghai', 'public_ip': '198.51.100.9'}):
            value = self.client.request('/v1/tripo/status')
            self.assertEqual(value, {'connected': True})
        with unittest.mock.patch.object(self.bridge.tripo, 'tools', side_effect=ValueError(
            'Upload at https://s3.bj.bcebos.com/private?token=secret failed in Asia/Shanghai')):
            with self.assertRaises(ValueError) as error: self.client.request('/v1/tripo/tools')
            self.assertNotIn('bcebos', str(error.exception))
            self.assertNotIn('secret', str(error.exception))
            self.assertNotIn('Shanghai', str(error.exception))
    def test_auth_origin_peer_and_unknown_routes(self):
        for headers in [{},{'Authorization':'Bearer '+'a'*64,'Origin':'https://foreign.invalid'}]:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(self.url+'/v1/status',headers=headers))
            self.assertEqual(error.exception.code,403)
        self.config['allowed_peers']=[]
        with self.assertRaises(ValueError):self.client.call('gpu_status',{})
        self.config['allowed_peers']=['127.0.0.1']
        with self.assertRaises(ValueError):self.client.request('/arbitrary-shell')
    def test_exposed_parameters_and_idempotence(self):
        first=self.submit();second=self.submit();self.assertEqual(first['id'],second['id']);self.assertEqual(self.adapter.submissions,1)
        with self.assertRaises(ValueError):self.client.call('run_workflow',{'workflow_id':'connection-test','parameters':{'color':124},'request_id':'b'*32})
        for parameters in [{'other':1},{'color':True},{'color':-1},{'color':1e100}]:
            with self.assertRaises(ValueError):apply_parameters(self.workflow,parameters)
        self.assertEqual(self.workflow['prompt']['1']['inputs']['color'],3368652)
        with self.assertRaises(ValueError):self.client.call('run_workflow',{'workflow_id':'../../private','parameters':{}})
    def test_failed_workflow_can_reuse_request_id_and_keeps_older_attempt(self):
        first=self.submit();old=self.bridge.jobs[first['id']]
        self.adapter.states[old['prompt_id']]={'status':'failed','error':'Fixture failure','artifacts':[]}
        self.assertEqual(self.client.call('job_status',{'job_id':old['id']})['status'],'failed')
        retry=self.submit();self.assertNotEqual(retry['id'],old['id']);self.assertEqual(retry['attempt'],2);self.assertEqual(retry['retry_of'],old['id'])
        self.assertEqual(self.submit()['id'],retry['id']);self.assertEqual(self.adapter.submissions,2)
        new=self.bridge.jobs[retry['id']];self.adapter.complete(new['prompt_id']);self.bridge.inspect(new['id'])
        restored=Bridge(self.config,self.adapter)
        value=restored.submit({'workflow_id':'connection-test','parameters':{'color':123},'request_id':'b'*32})
        self.assertEqual(value['id'],new['id']);self.assertEqual(value['status'],'succeeded')
        self.assertEqual(restored.jobs[old['id']]['status'],'failed');self.assertEqual(self.adapter.submissions,2)
    def test_uncertain_workflow_request_is_not_resubmitted(self):
        first=self.submit();job=self.bridge.jobs[first['id']];job['status']='unknown';self.bridge.save(job)
        self.assertEqual(self.submit()['id'],job['id']);self.assertEqual(self.adapter.submissions,1)
    def test_artifacts_owned_download_no_overwrite_and_restore(self):
        created=self.submit();job=self.bridge.jobs[created['id']];self.adapter.complete(job['prompt_id'])
        status=self.client.call('job_status',{'job_id':job['id']});self.assertEqual(status['status'],'succeeded')
        args={'job_id':job['id'],'index':0,'destination_dir':str(self.root/'vps-files')}
        one=self.client.call('fetch_artifact',args);two=self.client.call('fetch_artifact',args)
        self.assertNotEqual(one['path'],two['path']);self.assertEqual(pathlib.Path(one['path']).read_bytes(),self.adapter.bytes)
        self.assertEqual(one['sha256'],hashlib.sha256(self.adapter.bytes).hexdigest())
        self.assertEqual(one['timestamp_source'],'receiver')
        self.assertAlmostEqual(pathlib.Path(one['path']).stat().st_mtime,datetime.fromisoformat(one['saved_at']).timestamp(),places=4)
        restored=Bridge(self.config,self.adapter);self.assertEqual(restored.inspect(job['id'])['status'],'succeeded')
        with self.assertRaises(ValueError):self.client.call('fetch_artifact',{'job_id':'0'*32,'index':0})
    def test_download_timestamp_uses_receiver_timezone_without_shifting_the_instant(self):
        file=self.root/'received.flac';file.write_bytes(b'flac')
        saved=datetime(2026,10,26,9,30,0,tzinfo=timezone(timedelta(hours=5,minutes=45)))
        with unittest.mock.patch.object(client_module,'datetime') as clock:
            clock.now.return_value.astimezone.return_value=saved
            receipt=client_module.download_receipt(file,4,'checksum')
        self.assertTrue(receipt['saved_at'].endswith('+05:45'))
        self.assertEqual(file.stat().st_mtime,saved.timestamp())
        self.assertEqual(receipt['timestamp_source'],'receiver')
    def test_native_and_project_downloads_share_receiver_timestamps(self):
        ident=uuid.uuid4().hex
        project_root=self.root/'project';project_root.mkdir()
        self.config['native']={'projects':[{'id':'fixture','name':'Fixture','root':str(project_root),'enabled':True}]}
        self.bridge.native.jobs[ident]={'id':ident,'project_id':'fixture','engine':'godot','operation':'capture','status':'succeeded','created_at':1,'artifacts':[{'index':0,'filename':'shot.png','file':ident+'-0.png'}]}
        folder=self.bridge.native.root/'artifacts';folder.mkdir(exist_ok=True);(folder/(ident+'-0.png')).write_bytes(b'png')
        native=self.client.call('fetch_native_artifact',{'job_id':ident,'index':0,'destination_dir':str(self.root/'native-vps')})
        with unittest.mock.patch.object(self.client,'request',return_value=FakeResponse(b'project')):
            project=self.client.download_project({'project_id':'fixture','path':'model.glb','destination_dir':str(self.root/'project-vps')})
        for receipt in (native,project):
            self.assertEqual(receipt['timestamp_source'],'receiver')
            self.assertAlmostEqual(pathlib.Path(receipt['path']).stat().st_mtime,datetime.fromisoformat(receipt['saved_at']).timestamp(),places=4)
    def test_cached_success_with_missing_artifacts_is_recovered_without_regeneration(self):
        created=self.submit();job=self.bridge.jobs[created['id']];self.adapter.complete(job['prompt_id'])
        job.update(status='succeeded',artifacts=[]);self.bridge.save(job)
        restored=Bridge(self.config,self.adapter)
        recovered=restored.inspect(job['id'])
        self.assertEqual(recovered['status'],'succeeded');self.assertEqual(len(recovered['artifacts']),1)
        self.assertEqual(self.adapter.submissions,1)
        download=self.client.call('fetch_artifact',{'job_id':job['id'],'index':0,'destination_dir':str(self.root/'recovered')})
        self.assertEqual(pathlib.Path(download['path']).read_bytes(),self.adapter.bytes)
    def test_missing_history_does_not_downgrade_cached_success(self):
        created=self.submit();job=self.bridge.jobs[created['id']];job.update(status='succeeded',artifacts=[]);self.bridge.save(job)
        self.adapter.states[job['prompt_id']]={'status':'unknown'}
        self.assertEqual(self.bridge.inspect(job['id'])['status'],'succeeded')
        with unittest.mock.patch.object(self.adapter,'inspect',side_effect=ValueError('unavailable')):
            self.assertEqual(self.bridge.inspect(job['id'])['status'],'succeeded')
        self.assertEqual(self.adapter.submissions,1)
    def test_cancel_only_owned_pending(self):
        created=self.submit();job=self.bridge.jobs[created['id']]
        self.adapter.states[job['prompt_id']]={'status':'running'}
        with self.assertRaises(ValueError):self.client.call('cancel_pending_job',{'job_id':job['id']})
        self.assertEqual(self.adapter.cancelled,[])
        self.adapter.states[job['prompt_id']]={'status':'queued'}
        self.assertEqual(self.client.call('cancel_pending_job',{'job_id':job['id']})['status'],'cancelled')
    def test_upload_and_bad_file(self):
        file=self.root/'input.png';file.write_bytes(b'png')
        result=self.client.call('upload_input',{'path':str(file)});self.assertEqual(result['bytes'],3)
        with self.assertRaises(ValueError):self.client.request('/v1/assets',{'filename':'../x.png','content_base64':'eA=='})
    def test_mcp_real_stdio_and_tools(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'gpu_status','arguments':{}}},
                  {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'run_workflow','arguments':{'workflow_id':'connection-test','unexpected':'x'}}}]
        result=subprocess.run([sys.executable,str(pathlib.Path(__file__).parent/'plugin/client.py'),'--config',str(self.client_config)],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);lines=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(lines),4);self.assertEqual(len(lines[1]['result']['tools']),8)
        self.assertFalse(lines[2]['result']['isError']);self.assertTrue(lines[3]['result']['isError'])
        self.assertNotIn(self.config['token'],result.stdout+result.stderr)
    def test_invalid_graph_and_endpoint(self):
        with self.assertRaises(ValueError):validate_workflow({'id':'test','prompt':{'nodes':[]}})
        invalid=copy.deepcopy(self.workflow);invalid['parameters']['bad']={'node':'2','input':'images','type':'string'}
        with self.assertRaises(ValueError):validate_workflow(invalid)
        bad=self.root/'bad.json';bad.write_text(json.dumps({'url':'http://example.com','token':'a'*64}))
        with self.assertRaises(ValueError):client_module.Client(bad)
    def test_hardware_metadata_is_not_forwarded(self):
        result=self.client.call('gpu_status',{})
        encoded=json.dumps(result)
        self.assertNotIn('devices',encoded);self.assertNotIn('test GPU',encoded);self.assertNotIn('vram',encoded)
    def test_privacy_guard_fails_closed(self):
        self.client.require_private_metadata=True
        with unittest.mock.patch.object(client_module.socket,'AF_UNIX',1,create=True), unittest.mock.patch.object(client_module.socket,'socket') as factory:
            factory.return_value.connect.side_effect=PermissionError()
            self.client.privacy_check()
            factory.return_value.connect.side_effect=None
            with self.assertRaisesRegex(ValueError,'Privacy prerequisite'):self.client.privacy_check()
            factory.return_value.connect.side_effect=FileNotFoundError()
            with self.assertRaisesRegex(ValueError,'could not be verified'):self.client.privacy_check()
    def test_local_admin_isolated_and_explicit_import(self):
        from admin import start_admin
        admin=start_admin(self.bridge,0);url='http://127.0.0.1:'+str(admin.server_port)
        try:
            with urllib.request.urlopen(url) as response:html=response.read().decode()
            import re
            token=re.search("const token='([a-f0-9]+)'",html)[1]
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+'/api/workflows')
            error.exception.close()
            workflow=copy.deepcopy(self.workflow);workflow['id']='approved-copy'
            headers={'X-Admin-Token':token,'Content-Type':'application/json','Origin':url}
            request=urllib.request.Request(url+'/api/import',data=json.dumps({'workflow':workflow}).encode(),headers=headers)
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,201)
            self.assertTrue(any(item['id']=='approved-copy' for item in self.bridge.catalog()))
            bad=urllib.request.Request(url+'/api/import',data=json.dumps({'workflow':workflow}).encode(),headers={**headers,'Origin':'https://foreign.invalid'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(bad)
            self.assertEqual(error.exception.code,403);error.exception.close()
        finally:admin.shutdown();admin.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
