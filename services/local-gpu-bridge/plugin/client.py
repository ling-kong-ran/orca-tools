"""MCP stdio client, runs on the VPS. Never logs the bridge credential."""
import argparse, base64, hashlib, ipaddress, json, os, pathlib, re, socket, sys, urllib.error, urllib.parse, urllib.request, uuid, concurrent.futures
from datetime import datetime


def download_receipt(target, size, checksum):
    # This client runs on the VPS: timestamp at completed receipt, not from the
    # Windows sender. Unix mtimes are absolute instants; the ISO receipt includes
    # the receiver's actual timezone so displays cannot mistake UTC for local time.
    saved = datetime.now().astimezone()
    timestamp = saved.timestamp()
    os.utime(target, (timestamp, timestamp))
    return {'path': str(target), 'bytes': size, 'sha256': checksum,
            'saved_at': saved.isoformat(), 'timezone': str(saved.tzinfo),
            'timestamp_source': 'receiver'}

def user_home():
    # Orca gives each Claude account a separate HOME. Bridge config belongs to the OS user.
    try:
        import pwd
        return pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, AttributeError): return pathlib.Path.home()

def schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}

def tool(name, description, properties=None, required=None, readonly=True):
    return {'name': name, 'description': description, 'inputSchema': schema(properties, required),
            'annotations': {'readOnlyHint': readonly, 'destructiveHint': False, 'openWorldHint': False}}

STR = {'type': 'string'}
TOOLS = [
    tool('gpu_status', 'Check worker availability and queue counts. Does not return IP addresses, hostnames, hardware models, memory sizes or software versions.'),
    tool('list_workflows', 'List saved local ComfyUI workflows and imported workflows, availability, required asset parameters, and editable parameter types and bounds. Saved workflows are discovered automatically.'),
    tool('run_workflow', 'Queue one approved local ComfyUI workflow. Returns a job id immediately. Only exposed parameters can change. Reuse request_id to recover an uncertain submission without duplicating it.',
         {'workflow_id': STR, 'parameters': {'type': 'object'}, 'request_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}, ['workflow_id'], False),
    tool('list_jobs', 'List the last 100 jobs created through this bridge.'),
    tool('job_status', 'Refresh a bridge job and list the artifacts produced by that job.', {'job_id': STR}, ['job_id']),
    tool('cancel_pending_job', 'Cancel only this bridge job if it is still queued. Running jobs are not interrupted.', {'job_id': STR}, ['job_id'], False),
    tool('upload_input', 'Copy an image, audio, video or 3D asset from an absolute VPS path to the ComfyUI input folder, up to 32 MB. Returns a reference for exposed image/input parameters.', {'path': STR}, ['path'], False),
    tool('fetch_artifact', 'Download one completed job artifact onto the VPS using an exclusive filename. Returns the absolute saved path and SHA-256.',
         {'job_id': STR, 'index': {'type': 'integer', 'minimum': 0}, 'destination_dir': STR}, ['job_id','index'], False)
]

NATIVE_COMMON = [
    tool('local_projects','List approved local rendering projects. Names, Git settings and ids only; no local absolute paths.'),
    tool('local_status','Check Godot/Blender availability and network-isolation readiness. No hardware or public network information.'),
    tool('project_files','List approved project files, excluding secrets, executables, caches and Git metadata.',{'project_id':STR,'prefix':STR,'offset':{'type':'integer'},'limit':{'type':'integer'}},['project_id']),
    tool('read_project_file','Read one small project text file. Local addresses and absolute paths are redacted.',{'project_id':STR,'path':STR},['project_id','path']),
    tool('download_project_file','Download one approved local project file, such as a generated GLB, blend scene or screenshot, onto the VPS. Does not expose arbitrary local files.',{'project_id':STR,'path':STR,'destination_dir':STR},['project_id','path']),
    tool('project_git','Git is the only project sync path. status reads branch/head/change counts. fetch updates the configured remote branch. pull fetches then resets the local render mirror to that branch, backing up local edits first. Commit and push development changes on the VPS before rendering; local tracked edits may be discarded. pull/fetch return a native task id. No shell, arbitrary Git args, remote URL changes, commit or push are exposed.',{'project_id':STR,'operation':{'type':'string','enum':['status','fetch','pull']},'request_id':STR},['project_id'],False),
    tool('native_job_status','Check a native Godot or Blender task and its generated artifacts.',{'job_id':STR},['job_id']),
    tool('fetch_native_artifact','Download a completed native render artifact to an exclusive file on the VPS and verify SHA-256.',{'job_id':STR,'index':{'type':'integer'},'destination_dir':STR},['job_id','index'],False)
]
GODOT_TOOLS = NATIVE_COMMON + [
    tool('run_project_script','Execute a synchronized project GDScript, including tools/shots.gd screenshot galleries. Project script access and native network isolation are required. user_args follow --; use project_subdir=client for a client-rooted script. output_paths selects generated project artifacts to collect (default docs/shots). Gallery Godot/Go/server process calls are brokered; no generic shell is exposed.', {'project_id':STR,'script':STR,'user_args':{'type':'array','items':STR},'timeout_seconds':{'type':'integer'},'output_paths':{'type':'array','items':STR},'project_subdir':STR,'headless':{'type':'boolean'},'request_id':STR},['project_id','script'],False),
    tool('capture_scene','Run an existing scene from the approved local Godot project using its GPU, then capture a PNG. Supports scene-specific user_args such as --outfits and --view; these follow the Godot -- separator. Use run_project_script for project screenshot galleries or custom GDScript. Project scripts run locally; only synchronize trusted project code. Requires native network isolation.',
         {'project_id':STR,'scene':STR,'width':{'type':'integer'},'height':{'type':'integer'},'wait_seconds':{'type':'number'},'user_args':{'type':'array','items':STR},'renderer':{'type':'string','enum':['forward_plus','mobile','gl_compatibility']},'request_id':STR},['project_id'],False)
]
BLENDER_TOOLS = NATIVE_COMMON + [
    tool('blender_operation','Control the dedicated local Blender instance using typed operations or Python. execute_code {code,parameters?} executes Python with bpy, project_root, parameters; only an execution receipt is returned; run_script {path,user_args?,parameters?} runs a synchronized project .py file. Script access must be enabled. No generic shell tool. Arguments: scene_info {} returns objects and capabilities.vrm_import/vrm_export; open/save {path relative to project, replace? for save}; import_asset {path, including .vrm with the installed VRM extension}; export_asset {path .glb, .obj or .vrm,replace?}; create_primitive {kind:cube|sphere|plane|cylinder|cone|torus|monkey,name?,location?,rotation?,scale?}; set_transform {name,location?,rotation?,scale?}; set_material {name,color:[r,g,b,a],roughness?,metallic?}; set_camera {location,target?,lens?}; delete_object {name}; render {engine:cycles|eevee,width?,height?,samples?}. Vectors have three numbers; rotations are radians. Returns a task id. Requires native network isolation.',
         {'project_id':STR,'operation':{'type':'string','enum':['scene_info','open','save','import_asset','export_asset','create_primitive','set_transform','set_material','set_camera','delete_object','render','execute_code','run_script']},'arguments':{'type':'object'},'request_id':STR},['project_id','operation'],False)
]

VROID_TOOLS = NATIVE_COMMON[:6] + [
    tool('vroid_tools','List supported VRoid operations and their argument fields. VRoid Studio uses a managed local editor; VRM export is not available in the upstream adapter.'),
    tool('vroid_operation','Control local VRoid Studio: create/open characters, face/body/hair/outfit presets, sliders and colors, camera, preview-only screenshots, and save .vroid. First read vroid_tools; use help for details. state reports editor_connected, model_ready and phase: awaiting_model means the editor is running WITHOUT an open character. Call create or open next; waiting cannot load a character. open/save paths are relative to an approved project. save requires path; replace=true allows overwrite. main_menu requires discard_changes=true after saving. screenshot/previews only mode=inline. Text metadata is filtered; images contain only the model preview. No shell, raw commands or whole-window screenshots. A timed-out edit may still be running: query status before repeating.',
         {'project_id':STR,'operation':{'type':'string','enum':['state','status','sections','create','open','save','categories','enter','presets','select_preset','set_param','camera','screenshot','preset_preview_list','preset_preview_range','main_menu','help']},'arguments':{'type':'object'}},['project_id','operation'],False)
]

def vroid_state_result(result, operation):
    if operation not in ('state','status') or result.get('isError'):return result
    for item in result.get('content',[]):
        if item.get('type')!='text':continue
        try:value=json.loads(item.get('text',''))
        except (TypeError,ValueError):continue
        if not isinstance(value,dict):continue
        if operation=='state' and type(value.get('ready'))is bool and type(value.get('in_edit'))is bool:
            value['editor_connected']=True
            value['model_ready']=value.pop('ready')
            if value.get('updating'):
                value['phase']='updating_model'
                value['next_action']='Wait for the current model update; do not repeat its mutation.'
            elif not value['in_edit']:
                value['phase']='awaiting_model'
                value['next_action']='The editor is running. No character is open. Call create(gender=female|male) or open(path) next. Do not wait for model_ready before creating/opening a character.'
            elif value['model_ready']:
                value['phase']='editing'
                value['next_action']='The character is ready for editing, camera operations, previews and saving.'
            else:
                value['phase']='loading_model'
                value['next_action']='A character is opening. Check status/state after a short delay; do not repeat open/create.'
        elif operation=='status':
            value['editor_connected']=True
            value['next_action']='This is the command queue, not model readiness. Use state to decide whether to create/open a character. An empty queue does not mean the editor is still starting.'
        else:continue
        item['text']=json.dumps(value,ensure_ascii=False)
    return result

def source_file_allowed(relative):
    path=pathlib.PurePosixPath(relative)
    deny={'.git','.godot','.svn','node_modules','__pycache__','.ssh','.codex','.claude','.agent_bridge','saves'}
    names={'credentials.json','config.json','settings.json','secrets.json','id_rsa','id_ed25519'}
    suffixes={'.exe','.dll','.bat','.cmd','.ps1','.sh','.vbs','.com','.scr','.lnk','.pem','.key','.pfx','.p12'}
    return bool(relative) and not path.is_absolute() and '\\' not in relative and ':' not in relative and not any(p in ('','..','.') or p.lower() in deny or p.lower() in names or p.lower().startswith('.env') for p in path.parts) and path.suffix.lower() not in suffixes

def file_digest(file):
    h=hashlib.sha256()
    with file.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

class Client:
    def __init__(self, config_path):
        config = json.loads(pathlib.Path(config_path).read_text(encoding='utf-8'))
        parsed = urllib.parse.urlsplit(config['url'])
        try: host = ipaddress.ip_address(parsed.hostname)
        except ValueError: raise ValueError('Bridge endpoint must use a literal Tailscale IP.') from None
        if parsed.scheme not in ('http', 'https') or (host not in ipaddress.ip_network('100.64.0.0/10') and not host.is_loopback) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Bridge endpoint must be a loopback/Tailscale URL without credentials or a path.')
        if not isinstance(config.get('token'), str) or len(config['token']) < 32: raise ValueError('Invalid bridge credential.')
        self.base = config['url'].rstrip('/'); self.token = config['token']
        self.require_private_metadata = config.get('require_private_tailnet_metadata', False)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def privacy_check(self):
        if not self.require_private_metadata: return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect('/run/tailscale/tailscaled.sock')
        except PermissionError: return
        except OSError:
            raise ValueError('Network privacy could not be verified. Check the local Tailscale service and the root privacy setup.') from None
        else:
            raise ValueError('Privacy prerequisite is not satisfied: this VPS account can query public Tailscale endpoints. Run the supplied root privacy setup before enabling GPU access.')
        finally: probe.close()
    def request(self, route, body=None, stream=False):
        self.privacy_check()
        request = urllib.request.Request(self.base+route, data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/json'})
        try:
            response = self.opener.open(request, timeout=300 if route=='/v1/vroid/call' else 90 if stream or body is not None else 20)
            if stream: return response
            with response: return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 403:
                error.close(); raise ValueError('Bridge access denied. Check the configured token and allowed Tailscale peer.') from None
            try: detail = json.loads(error.read(8192)).get('error', 'Bridge request failed.')
            except (ValueError, AttributeError): detail = 'Bridge request failed.'
            finally: error.close()
            raise ValueError(str(detail)[:2000]) from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError('The local GPU computer is unreachable. Check that this computer, Tailscale and Local GPU Bridge are running; keep the same request_id when retrying a submission.') from None
    def call(self, name, args):
        if name=='vroid_tools':return self.request('/v1/vroid/tools')
        if name=='vroid_operation':return vroid_state_result(self.request('/v1/vroid/call',args),args['operation'])
        if name=='local_projects':return self.request('/v1/native/projects')
        if name=='local_status':return self.request('/v1/native/status')
        if name=='project_files':return self.request('/v1/native/files',args)
        if name=='read_project_file':return self.request('/v1/native/read',args)
        if name=='download_project_file':return self.download_project(args)
        if name=='project_git':
            body=dict(args)
            if body.get('operation','status')!='status':body.setdefault('request_id',uuid.uuid4().hex)
            try:return self.request('/v1/native/git',body)
            except ValueError as e:raise ValueError(str(e)+(' request_id='+body['request_id'] if 'request_id' in body else '')) from None
        if name=='native_job_status':
            if not re.fullmatch('[a-f0-9]{32}',args['job_id']):raise ValueError('Invalid job id.')
            return self.request('/v1/native/jobs/'+args['job_id'])
        if name in ('capture_scene','run_project_script','blender_operation'):
            body={'project_id':args['project_id'],'engine':'blender' if name=='blender_operation' else 'godot','operation':('capture' if name=='capture_scene' else 'script') if name!='blender_operation' else args['operation'],
                  'arguments':{k:v for k,v in args.items() if k in ('scene','width','height','wait_seconds','renderer','user_args')} if name=='capture_scene' else {k:v for k,v in args.items() if k in ('script','user_args','timeout_seconds','output_paths','project_subdir','headless')} if name=='run_project_script' else args.get('arguments',{}),'request_id':args.get('request_id') or uuid.uuid4().hex}
            try:return self.request('/v1/native/jobs',body)
            except ValueError as e:raise ValueError(str(e)+' request_id='+body['request_id']) from None
        if name == 'gpu_status': return self.request('/v1/status')
        if name == 'list_workflows': return self.request('/v1/workflows')
        if name == 'list_jobs': return self.request('/v1/jobs')
        if name == 'run_workflow':
            args = dict(args); args.setdefault('parameters', {}); args.setdefault('request_id', uuid.uuid4().hex)
            try: return self.request('/v1/jobs', args)
            except ValueError as error: raise ValueError(str(error) + ' request_id=' + str(args['request_id'])) from None
        ident = args.get('job_id', '')
        if name in ('job_status','cancel_pending_job','fetch_artifact','fetch_native_artifact') and not re.fullmatch('[a-f0-9]{32}',ident): raise ValueError('Invalid job id.')
        if name == 'job_status': return self.request('/v1/jobs/'+ident)
        if name == 'cancel_pending_job': return self.request('/v1/jobs/'+ident+'/cancel', {})
        if name == 'upload_input':
            file = pathlib.Path(args['path'])
            if not file.is_absolute() or not file.is_file() or file.stat().st_size > 32*1024**2: raise ValueError('Input must be an absolute existing file of at most 32 MB.')
            # Unicode filenames are normalized to a portable name; bytes are unchanged.
            suffix = file.suffix.lower(); filename = 'input-' + uuid.uuid4().hex + suffix
            return self.request('/v1/assets', {'filename': filename, 'content_base64': base64.b64encode(file.read_bytes()).decode()})
        if name in ('fetch_artifact','fetch_native_artifact'):
            prefix='/v1/native' if name=='fetch_native_artifact' else '/v1'
            index = args['index']
            if type(index) is not int or index < 0: raise ValueError('Invalid artifact index.')
            job = self.request(prefix+'/jobs/'+ident)
            artifact = next((a for a in job['artifacts'] if a['index'] == index), None)
            if job['status'] != 'succeeded' or not artifact: raise ValueError('Artifact is not ready.')
            folder = pathlib.Path(args.get('destination_dir') or str(pathlib.Path.cwd()/'local-gpu-outputs'))
            if not folder.is_absolute(): raise ValueError('destination_dir must be absolute.')
            folder.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', artifact['filename'])[:150].lstrip('.') or 'output.bin'
            target = folder/(ident[:8]+'-'+str(index)+'-'+safe_name)
            partial = folder/('.'+uuid.uuid4().hex+'.part'); digest = hashlib.sha256(); size = 0
            try:
                with self.request(prefix+'/artifacts/'+ident+'/'+str(index), stream=True) as response, partial.open('xb') as output:
                    expected = int(response.headers.get('Content-Length', '-1'))
                    if expected < 0 or expected > 2*1024**3: raise ValueError('Invalid artifact size.')
                    while True:
                        chunk = response.read(1024*1024)
                        if not chunk: break
                        size += len(chunk)
                        if size > expected: raise ValueError('Artifact exceeded the announced size.')
                        output.write(chunk); digest.update(chunk)
                    if size != expected: raise ValueError('Artifact was truncated.')
                    output.flush(); os.fsync(output.fileno())
                # An exclusive hard link never overwrites a pre-existing output.
                attempt = 0
                while True:
                    candidate = target if attempt == 0 else target.with_name(target.stem+'-'+str(attempt)+target.suffix)
                    try: os.link(partial,candidate); target=candidate; break
                    except FileExistsError: attempt += 1
                return download_receipt(target, size, digest.hexdigest())
            finally: partial.unlink(missing_ok=True)
        raise ValueError('Unknown tool: '+name)

    def download_project(self,args):
        relative=args['path']
        if not source_file_allowed(relative):raise ValueError('This project file is not exposed.')
        folder=pathlib.Path(args.get('destination_dir') or str(pathlib.Path.cwd()/'local-project-files'))
        if not folder.is_absolute():raise ValueError('destination_dir must be absolute.')
        folder.mkdir(parents=True,exist_ok=True)
        name=re.sub('[^A-Za-z0-9._-]','_',pathlib.PurePosixPath(relative).name).lstrip('.')[:150] or 'file.bin'
        partial=folder/('.'+uuid.uuid4().hex+'.part');digest=hashlib.sha256();size=0
        route='/v1/native/project-file?'+urllib.parse.urlencode({'project_id':args['project_id'],'path':relative})
        try:
            with self.request(route,stream=True) as response,partial.open('xb') as output:
                expected=int(response.headers.get('Content-Length','-1'))
                if not 0<=expected<=2*1024**3:raise ValueError('Invalid project file size.')
                while data:=response.read(1024*1024):
                    size+=len(data)
                    if size>expected:raise ValueError('File exceeded announced size.')
                    output.write(data);digest.update(data)
                if size!=expected:raise ValueError('File transfer was truncated.')
            for attempt in range(10000):
                target=folder/(name if attempt==0 else str(attempt)+'-'+name)
                try:os.link(partial,target);break
                except FileExistsError:continue
            else:raise ValueError('No unused output filename is available.')
            return download_receipt(target, size, digest.hexdigest())
        finally:partial.unlink(missing_ok=True)

def check_args(definition, args):
    if not isinstance(args, dict): raise ValueError('Tool arguments must be an object.')
    fields = definition['inputSchema']['properties']
    if set(args)-set(fields): raise ValueError('Unexpected tool arguments.')
    if any(key not in args for key in definition['inputSchema']['required']): raise ValueError('Required tool argument is missing.')
    for key,value in args.items():
        kind = fields[key]['type']
        if kind == 'string' and not isinstance(value,str) or kind == 'integer' and type(value) is not int or kind == 'object' and not isinstance(value,dict): raise ValueError('Wrong type for '+key)
        if kind=='boolean' and type(value)is not bool or kind=='array' and not isinstance(value,list) or kind=='number' and type(value)not in (int,float):raise ValueError('Wrong type for '+key)
        if 'enum' in fields[key] and value not in fields[key]['enum']:raise ValueError('Invalid option for '+key)

def serve(client,tools=None):
    tools=TOOLS if tools is None else tools
    for raw in sys.stdin.buffer:
        request = None
        try:
            if len(raw) > 1024*1024: raise ValueError('MCP message is too large.')
            request = json.loads(raw)
            if not isinstance(request, dict): raise ValueError('Expected a JSON-RPC object.')
            ident = request.get('id'); method = request.get('method'); params = request.get('params') or {}
            if 'id' not in request: continue
            if method == 'initialize':
                version = params.get('protocolVersion')
                if version not in ('2024-11-05','2025-03-26','2025-06-18'): version='2025-03-26'
                result = {'protocolVersion':version,'capabilities':{'tools':{}},'serverInfo':{'name':'local-gpu','version':'1.5.2'},
                          'instructions':'Use only listed workflows/projects and exposed tools. Native development stays on the VPS: commit and push on the VPS, then use project_git pull or automatic Git update before rendering. Git is the only project synchronization method; local tracked edits are disposable and backed up before reset. Project GDScript and Blender Python are available when allow_scripts is enabled. No generic shell is exposed. Run native rendering only after network isolation is ready. Scripts run with local user file access; do not query host identity or network metadata. Poll job status with reasonable delays. Do not interrupt unrelated local jobs.'}
            elif method == 'ping': result = {}
            elif method == 'tools/list': result = {'tools': tools}
            elif method == 'tools/call':
                definition = next((t for t in tools if t['name'] == params.get('name')), None)
                if not definition: raise ValueError('Unknown tool.')
                try:
                    args = params.get('arguments') or {}; check_args(definition,args)
                    value = client.call(definition['name'],args)
                    result = value if definition['name']=='vroid_operation' else {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}], 'isError':False}
                except Exception as error:
                    result = {'content':[{'type':'text','text':str(error)[:2400]}], 'isError':True}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}),flush=True); continue
            print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result},ensure_ascii=False),flush=True)
        except Exception:
            ident = request.get('id') if isinstance(request,dict) else None
            print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32600,'message':'Invalid request'}}),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(user_home()/'.config/local-gpu-bridge/client.json'));parser.add_argument('--self-test',action='store_true');parser.add_argument('--namespace',choices=['comfyui','godot','blender','vroid'],default='comfyui');args=parser.parse_args()
    try:
        client=Client(args.config)
        if args.self_test:
            print(json.dumps({'status':client.call('gpu_status',{}),'catalog':client.call('list_workflows',{})},ensure_ascii=False));return
        serve(client,{'comfyui':TOOLS,'godot':GODOT_TOOLS,'blender':BLENDER_TOOLS,'vroid':VROID_TOOLS}[args.namespace])
    except Exception as error:
        print('Local GPU plugin: '+str(error)[:500],file=sys.stderr);sys.exit(1)

if __name__=='__main__': main()
