"""Project scheduler regressions with a deterministic host resource probe."""
from concurrent.futures import ThreadPoolExecutor
from importlib.util import spec_from_file_location, module_from_spec
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from native_control import NativeControl
from render_capacity import RenderCapacity


class Process:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def stop(self):
        self.alive = False

    def close(self):
        self.stop()


class Guard:
    def require(self, engine):
        pass

    def ready(self, engine):
        return True


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = {'data_dir':folder.name, 'native':{'unity_executable':'test','blender_executable':'test'}}
        self.native = NativeControl(self.config,guard=Guard())
        self.native.capacity = RenderCapacity(2,probe=lambda:4)
        self.projects = [self.native.workspace(uuid.uuid4().hex)['project_id'] for _ in range(2)]

    def test_two_unity_projects_launch_concurrently_and_stop_independently(self):
        barrier = threading.Barrier(2,timeout=4)
        launches = {}

        def launch(args, root, log, env, **kwargs):
            process = Process()
            launches[root] = (log,env['TEMP'],process)
            barrier.wait()
            return process

        self.native.process_factory = launch
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.native.unity.start,self.projects))
        self.assertEqual([result['project_id'] for result in results],self.projects)
        self.assertEqual(len(set(log for log,_,_ in launches.values())),2)
        self.assertEqual(len(set(temp for _,temp,_ in launches.values())),2)
        self.assertEqual(self.native.capacity.status()['in_use'],2)
        self.native.unity.stop(self.projects[0])
        self.assertTrue(self.native.unity.start(self.projects[1])['already_running'])
        self.assertEqual(self.native.capacity.status()['in_use'],1)
        self.native.unity.stop(self.projects[1])

    def test_two_blender_workers_receive_only_their_project_requests(self):
        barrier = threading.Barrier(2,timeout=4)
        workers = []
        spools = []
        def launch(command, project, log, env):
            process = Process()
            spool = Path(command[-1]).parent
            spools.append(spool)
            (spool/'ready.json').write_text('{}')
            def respond():
                barrier.wait()
                deadline = time.monotonic()+4
                while time.monotonic()<deadline:
                    requests = list(spool.glob('*.request.json'))
                    if requests:
                        output = requests[0].with_name(requests[0].name.replace('.request.','.response.'))
                        from native_control import atomic
                        atomic(output,{'ok':True,'result':{'owner':project.name}})
                        return
                    time.sleep(.01)
            worker = threading.Thread(target=respond,daemon=True)
            workers.append(worker)
            worker.start()
            return process
        self.native.process_factory = launch
        jobs = [self.native.queue({'engine':'blender','project_id':ident,'operation':'scene_info',
                    'request_id':uuid.uuid4().hex,'arguments':{}}) for ident in self.projects]
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            results = [self.native.job_status(j['id']) for j in jobs]
            if all(j['status']=='succeeded' for j in results):break
            time.sleep(.02)
        self.assertEqual([j['result']['owner'] for j in results],self.projects)
        self.assertEqual(len(set(spools)),2)
        self.native.stop_blender(self.projects[0])
        self.assertEqual(self.native.running_blenders(),[self.projects[1]])
        self.native.stop_blender(self.projects[1])
        for worker in workers: worker.join(1)

    def test_vroid_uses_distinct_verified_loopback_sessions(self):
        from native_vroid import VroidControl
        install = self.root/'studio'
        configs = install/'BepInEx/config'
        configs.mkdir(parents=True)
        (configs/'com.kokokoshka.vroidstudiomcp.servers.json').write_text(json.dumps({
            'enabled':True,'tcp':'127.0.0.1:17890','mcp':'127.0.0.1:17891','dev_tools':False,'debug_artifacts':False}))
        plugins = install/'BepInEx/plugins'
        plugins.mkdir()
        (plugins/'toolkit-export.json').write_text('{"project_sessions":true}')
        self.config['native']['vroid_executable'] = str(install/'studio.exe')
        barrier = threading.Barrier(2,timeout=4)
        endpoints = {}
        def launch(args,root,log,env,**kwargs):
            settings = json.loads(Path(env['VROID_SESSION_SETTINGS']).read_text())
            endpoints[settings['mcp']] = env['VROID_SESSION_ID']
            barrier.wait()
            return Process()
        def rpc(session,method,params=None,timeout=90):
            if method=='ping':
                return {'bridge_session':endpoints[f'127.0.0.1:{session.port}']}
            return {'isError':False,'content':[{'type':'text','text':'ready'}]}
        self.native.process_factory = launch
        with patch.object(VroidControl,'rpc',rpc),ThreadPoolExecutor(2) as pool:
            self.assertTrue(all(not r['isError'] for r in pool.map(
                lambda ident:self.native.vroid.call(ident,'state'),self.projects)))
        self.assertEqual(len(endpoints),2)
        self.assertEqual(len(set(endpoints.values())),2)
        for ident in self.projects:self.native.vroid.stop(ident)

    def test_shared_budget_and_resource_recovery(self):
        capacity = self.native.capacity
        a,b = self.projects
        process = Process()
        with self.native.operation(a,'unity') as (_,root):
            capacity.track(('unity',root,a),process)
        with self.native.operation(b,'godot'):
            self.assertEqual(capacity.status()['in_use'],2)
            with self.assertRaisesRegex(ValueError,'capacity'):
                with self.native.operation(a,'blender'):pass
            self.native.set_render_capacity(1)
            self.assertTrue(process.alive)
        capacity.probe = lambda:0
        capacity.sample_at = 0
        self.native.set_render_capacity(3)
        with self.assertRaisesRegex(ValueError,'capacity'):
            with self.native.operation(b,'godot'):pass
        capacity.probe = lambda:4
        capacity.sample_at = 0
        with self.native.operation(b,'godot'):
            self.assertEqual(capacity.status()['in_use'],2)
        self.assertEqual(NativeControl(self.config).capacity.maximum,3)
        self.assertNotIn('render_capacity',self.native.status())
        self.assertEqual(self.native.status(local=True)['render_capacity']['maximum'],3)
        for invalid in (0,33,True,'3',None):
            with self.assertRaises(ValueError):self.native.set_render_capacity(invalid)

    def test_project_queue_does_not_block_another_workspace_or_status(self):
        a,b = self.projects
        entered = threading.Event()
        def waiting_job():
            with self.native.operation(a):
                entered.set()
        with ThreadPoolExecutor(1) as pool:
            with self.native.operation(a):
                f = pool.submit(waiting_job)
                with self.native.operation(b):
                    self.assertFalse(entered.wait(.1))
                    self.assertFalse(self.native.unity.editor_state(a)['running'])
            f.result(timeout=2)
        self.assertTrue(entered.is_set())

    def test_workspace_is_idempotent_and_has_no_implicit_permissions(self):
        a,b = self.projects
        self.assertEqual(self.native.workspace(a.split('.')[1])['project_id'],a)
        item,root = self.native.project(a)
        self.assertFalse(item['allow_scripts'])
        self.assertNotEqual(root,self.native.project(b)[1])
        self.assertEqual(self.native.projects(),[])
        with self.assertRaises(ValueError):self.native.workspace('../private')
        with self.assertRaisesRegex(ValueError,'script access'):
            self.native.queue({'project_id':a,'engine':'blender','operation':'execute_code','arguments':{'code':'pass'}})

    def test_admin_capacity_is_persistent_and_local_only(self):
        import re
        from urllib.error import HTTPError
        from urllib.request import Request,urlopen
        from admin import start_admin
        from bridge import Bridge
        config_file=self.root/'local.json'
        config={**self.config,'_config_file':str(config_file)}
        bridge=Bridge(config)
        server=start_admin(bridge,port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url='http://127.0.0.1:'+str(server.server_port)
        with urlopen(url) as response:
            token=re.search("const token='([a-f0-9]+)'",response.read().decode())[1]
        route=url+'/api/native/render-capacity'
        body=b'{"maximum":5}'
        headers={'X-Admin-Token':token,'Content-Type':'application/json'}
        with self.assertRaises(HTTPError) as blocked:
            urlopen(Request(route,body,headers))
        self.assertEqual(blocked.exception.code,403)
        blocked.exception.close()
        with urlopen(Request(route,body,{**headers,'Origin':url})) as response:
            self.assertEqual(json.load(response)['maximum'],5)
        self.assertEqual(Bridge(json.loads(config_file.read_text())).native.capacity.maximum,5)
        self.assertNotIn('render_capacity',bridge.native.status())

    def test_stdio_multiplexes_blocked_calls_and_preserves_reply_ids(self):
        spec=spec_from_file_location('parallel_test_client',Path(__file__).parent/'plugin/client.py')
        client=module_from_spec(spec)
        spec.loader.exec_module(client)
        barrier = threading.Barrier(2,timeout=3)
        class Caller:
            def call(self,name,args):
                barrier.wait()
                return args['project_id']
        messages = [json.dumps({'id':i,'method':'tools/call','params':{'name':'unity_start','arguments':{'project_id':p}}})
                    for i,p in enumerate(self.projects)]
        incoming = type('Input',(),{'buffer':io.BytesIO(('\n'.join(messages)+'\n').encode())})()
        output = io.StringIO()
        with patch.object(client.sys,'stdin',incoming),patch.object(client.sys,'stdout',output):
            client.serve(Caller(),client.UNITY_TOOLS)
        replies = {r['id']:r['result'] for r in map(json.loads,output.getvalue().splitlines())}
        for i,p in enumerate(self.projects):
            self.assertFalse(replies[i]['isError'])
            self.assertEqual(json.loads(replies[i]['content'][0]['text']),p)
