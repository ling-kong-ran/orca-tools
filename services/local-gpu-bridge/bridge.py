"""Local GPU task bridge. Standard library only; no arbitrary command endpoint."""
import argparse, base64, copy, hashlib, hmac, http.server, io, json, logging
import logging.handlers, mimetypes, os, pathlib, re, threading, time, urllib.error
import urllib.parse, urllib.request, uuid, shutil
from workflow_library import WorkflowLibrary
from native_control import NativeControl
from native_tripo import TripoControl
from remote_privacy import remote_json
from job_reuse import latest_attempt, attempt_fields

SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HEX = re.compile(r'^[a-f0-9]{32}$')
MAX_BODY = 48 * 1024 * 1024
_INSTANCE_LOCK = None


def acquire_instance_lock(root):
    """Keep one bridge per data directory, including concurrent Windows launches."""
    global _INSTANCE_LOCK
    handle = (pathlib.Path(root) / 'instance.lock').open('a+b')
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('Local GPU Bridge is already running.') from None
    _INSTANCE_LOCK = handle
    return handle

def atomic_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, file)

def safe_relative(value):
    return isinstance(value, str) and '\\' not in value and ':' not in value and not value.startswith('/') and all(x not in ('..', '.') for x in value.split('/'))

def validate_workflow(value):
    if not isinstance(value, dict) or not SLUG.fullmatch(value.get('id', '')):
        raise ValueError('Workflow needs a lowercase id, name, prompt and parameters.')
    prompt = value.get('prompt')
    if not isinstance(prompt, dict) or not prompt or len(prompt) > 2000 or 'nodes' in prompt:
        raise ValueError('Use the ComfyUI API-format graph, not the editor-format workflow.')
    for node in prompt.values():
        if not isinstance(node, dict) or not isinstance(node.get('class_type'), str) or not isinstance(node.get('inputs'), dict):
            raise ValueError('Invalid API-format node.')
    for name, spec in value.get('parameters', {}).items():
        if not SLUG.fullmatch(name) or spec.get('type') not in ('string', 'integer', 'number', 'boolean'):
            raise ValueError('Invalid parameter name or type.')
        target = prompt.get(str(spec.get('node')), {}).get('inputs', {})
        if spec.get('input') not in target or isinstance(target[spec['input']], (list, dict)):
            raise ValueError('Parameters must reference existing literal inputs, not graph links.')
        if 'enum' in spec and (not isinstance(spec['enum'], list) or not spec['enum']):
            raise ValueError('Parameter enum must be a nonempty list.')
    return value

def apply_parameters(workflow, values):
    if not isinstance(values, dict): raise ValueError('parameters must be an object')
    prompt = copy.deepcopy(workflow['prompt'])
    import secrets
    for node,field in workflow.get('random_seeds',[]):
        prompt[node]['inputs'][field] = secrets.randbelow(2**53)
    specs = workflow.get('parameters', {})
    for name, value in values.items():
        if name not in specs: raise ValueError('Parameter is not exposed: ' + name)
        spec = specs[name]
        valid = {'string': isinstance(value, str), 'integer': type(value) is int,
                 'number': type(value) in (int, float), 'boolean': type(value) is bool}[spec['type']]
        if not valid: raise ValueError('Wrong type for ' + name)
        if isinstance(value, str) and len(value) > spec.get('maxLength', 16000): raise ValueError(name + ' is too long')
        if type(value) in (int, float):
            import math
            if not math.isfinite(value) or value < spec.get('minimum', -1e16) or value > spec.get('maximum', 1e16): raise ValueError(name + ' is out of range')
        if 'enum' in spec and value not in spec['enum']: raise ValueError('Invalid option for ' + name)
        if spec.get('asset') and (not safe_relative(value) or not value or re.match(r'^[a-zA-Z]+:',value)):
            raise ValueError('Asset inputs must use a relative ComfyUI input reference.')
        prompt[str(spec['node'])]['inputs'][spec['input']] = value
    return prompt

class ComfyAdapter:
    kind = 'comfyui.workflow'
    def __init__(self, base):
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('', '/'):
            raise ValueError('ComfyUI URL must be a local loopback HTTP address.')
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(self, route, body=None, timeout=15):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + route, data=data, headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            error.close()
            raise ValueError('ComfyUI rejected the request. Review the local ComfyUI log for details.') from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError('ComfyUI is unavailable. Start ComfyUI on this computer and retry.') from None
    def status(self):
        queue = self.request('/queue')
        return {'online': True,
                'running': len(queue.get('queue_running', [])), 'pending': len(queue.get('queue_pending', []))}
    def submit(self, prompt, client_id):
        result = self.request('/prompt', {'prompt': prompt, 'client_id': client_id})
        if not isinstance(result.get('prompt_id'), str): raise ValueError('ComfyUI did not return a prompt id.')
        return result['prompt_id']
    def history_status(self, history, prompt_id):
        if prompt_id in history:
            item = history[prompt_id]; status = item.get('status', {})
            if status.get('status_str') == 'error':
                message = 'Workflow execution failed. Review the local ComfyUI log for details.'
                return {'status': 'failed', 'error': message, 'artifacts': []}
            if status.get('completed'):
                artifacts = []; seen = set()
                def visit(value):
                    if isinstance(value, dict):
                        name = value.get('filename'); folder = value.get('subfolder', '')
                        # Windows save nodes return backslashes; normalize only the
                        # relative subfolder, then retain the existing traversal checks.
                        if isinstance(folder,str): folder = folder.replace('\\','/')
                        if value.get('type', 'output') == 'output' and isinstance(name, str) and name and safe_relative(name) and '/' not in name and safe_relative(folder):
                            key = (name, folder)
                            if key not in seen:
                                seen.add(key); artifacts.append({'filename': name, 'subfolder': folder, 'type': 'output'})
                        for child in value.values(): visit(child)
                    elif isinstance(value, list):
                        for child in value: visit(child)
                visit(item.get('outputs', {}))
                return {'status': 'succeeded', 'artifacts': artifacts}
        return None
    def inspect(self, prompt_id):
        history_route = '/history/' + urllib.parse.quote(prompt_id, safe='')
        result = self.history_status(self.request(history_route), prompt_id)
        if result: return result
        queue = self.request('/queue')
        for kind, state in [('queue_running', 'running'), ('queue_pending', 'queued')]:
            if any(len(entry) > 1 and entry[1] == prompt_id for entry in queue.get(kind, [])):
                return {'status': state}
        # Completion can land between the history request and the queue request.
        result = self.history_status(self.request(history_route), prompt_id)
        if result: return result
        return {'status': 'unknown', 'message': 'No queue/history entry. The backend may have restarted; do not blindly resubmit.'}
    def cancel_pending(self, prompt_id):
        queue = self.request('/queue')
        if any(entry[1] == prompt_id for entry in queue.get('queue_running', [])):
            raise ValueError('This job is running. A global interrupt could stop another local task, so it is not exposed.')
        if any(entry[1] == prompt_id for entry in queue.get('queue_pending', [])):
            self.request('/queue', {'delete': [prompt_id]}); return True
        return False
    def artifact(self, item):
        query = urllib.parse.urlencode(item)
        return self.opener.open(self.base + '/view?' + query, timeout=60)
    def upload(self, filename, content):
        boundary = 'bridge-' + uuid.uuid4().hex
        name = uuid.uuid4().hex + '-' + filename
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content +
                f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="subfolder"\r\n\r\nlocal-gpu-bridge\r\n--{boundary}--\r\n'.encode())
        request = urllib.request.Request(self.base + '/upload/image', data=body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with self.opener.open(request, timeout=60) as response: value = json.load(response)
        return {'name': value['name'], 'subfolder': value.get('subfolder', ''), 'reference': '/'.join(filter(None, [value.get('subfolder'), value['name']]))}

class Bridge:
    def __init__(self, config, adapter=None):
        self.config = config; self.root = pathlib.Path(config['data_dir'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.adapters = {'comfyui.workflow': adapter or ComfyAdapter(config.get('comfy_url', 'http://127.0.0.1:8188'))}
        self.library = WorkflowLibrary(config.get('workflow_dirs',[]),self.adapters['comfyui.workflow'])
        def save_config():
            if config.get('_config_file'):
                atomic_json(pathlib.Path(config['_config_file']),{k:v for k,v in config.items() if not k.startswith('_')})
        self.native = NativeControl(config,save_config)
        self.tripo = TripoControl(config)
        if config.get('tripo'): self.tripo.start_keepalive()
        self.jobs = {}
        for file in (self.root/'jobs').glob('*.json'):
            try:
                job = json.loads(file.read_text(encoding='utf-8'))
                if HEX.fullmatch(job['id']): self.jobs[job['id']] = job
            except (ValueError, KeyError): pass
    def workflows(self):
        values = []
        for file in sorted((self.root/'workflows').glob('*.json')):
            value = validate_workflow(json.loads(file.read_text(encoding='utf-8')))
            if file.stem != value['id']: raise ValueError('Workflow filename and id must match.')
            values.append(value)
        return values + self.library.workflows()
    def catalog(self):
        return [{**{k: w.get(k, {}) for k in ('id', 'name', 'description', 'parameters')},
                 'source':w.get('source','imported'),'available':w.get('available',True),
                 'required_parameters':w.get('required_parameters',[]),
                 **({'unavailable_reason':w['unavailable_reason']} if 'unavailable_reason' in w else {})} for w in self.workflows()]
    def public(self, job):
        result = {k: job[k] for k in ('id', 'workflow_id', 'kind', 'status', 'created_at', 'updated_at')}
        for key in ('error', 'message'):
            if key in job: result[key] = job[key]
        for key in ('attempt','retry_of'):
            if key in job: result[key] = job[key]
        result['artifacts'] = [{'index': i, 'filename': item['filename']} for i, item in enumerate(job.get('artifacts', []))]
        return result
    def save(self, job):
        job['updated_at'] = time.time(); atomic_json(self.root/'jobs'/(job['id']+'.json'), job)
    def submit(self, body):
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not HEX.fullmatch(request_id): raise ValueError('A 32-character request_id is required.')
        parameters = body.get('parameters', {})
        fingerprint = hashlib.sha256(json.dumps({'workflow_id': body.get('workflow_id'), 'parameters': parameters}, sort_keys=True).encode()).hexdigest()
        with self.lock:
            existing = latest_attempt(self.jobs, request_id, fingerprint)
            if existing and existing['status'] != 'failed':
                return self.public(existing)
            workflow = next((w for w in self.workflows() if w['id'] == body.get('workflow_id')), None)
            if not workflow: raise ValueError('Unknown workflow. List the current saved workflows first.')
            if not workflow.get('available',True): raise ValueError(workflow.get('unavailable_reason','This workflow is currently unavailable.'))
            missing = [key for key in workflow.get('required_parameters',[]) if key not in parameters]
            if missing: raise ValueError('Provide these input asset parameters before running: '+', '.join(missing))
            prompt = apply_parameters(workflow, parameters)
            # Admission counts backend-active jobs; old finished jobs do not consume slots.
            active = 0
            for old in self.jobs.values():
                if old['status'] in ('queued', 'running'):
                    old.update(self.adapters[old['kind']].inspect(old['prompt_id'])); self.save(old)
                if old['status'] in ('submitting', 'queued', 'running', 'unknown'): active += 1
            if active >= self.config.get('max_active_jobs', 8): raise ValueError('Bridge job limit reached. Check existing jobs before submitting more.')
            job = {'id': uuid.uuid4().hex, 'request_id': request_id, 'fingerprint': fingerprint,
                   'workflow_id': workflow['id'], 'kind': 'comfyui.workflow', 'status': 'submitting',
                   'created_at': time.time(), 'updated_at': time.time(), 'artifacts': []}
            job.update(attempt_fields(existing))
            self.jobs[job['id']] = job; self.save(job)
            try:
                job['prompt_id'] = self.adapters[job['kind']].submit(prompt, 'local-gpu-bridge-' + job['id'])
                job['status'] = 'queued'; self.save(job)
            except Exception:
                job['status'] = 'unknown'; job['message'] = 'Submission was not acknowledged. Check the local queue before retrying.'; self.save(job)
                raise
            return self.public(job)
    def inspect(self, ident):
        with self.lock:
            if ident not in self.jobs: raise ValueError('Unknown bridge job.')
            job = self.jobs[ident]
            if job['status'] not in ('succeeded', 'failed', 'cancelled') and job.get('prompt_id'):
                job.update(self.adapters[job['kind']].inspect(job['prompt_id'])); self.save(job)
            elif job['status']=='succeeded' and not job.get('artifacts') and job.get('prompt_id'):
                # Repair old successful records whose Windows output paths were
                # discarded. Never resubmit or downgrade a cached success.
                try: recovered=self.adapters[job['kind']].inspect(job['prompt_id'])
                except ValueError: recovered=None
                if recovered and recovered.get('status')=='succeeded' and recovered.get('artifacts'):
                    job.update(recovered);self.save(job)
            return self.public(job)
    def cancel(self, ident):
        with self.lock:
            self.inspect(ident); job = self.jobs[ident]
            if job['status'] == 'queued' and self.adapters[job['kind']].cancel_pending(job['prompt_id']):
                latest = self.adapters[job['kind']].inspect(job['prompt_id'])
                if latest['status'] == 'unknown': job['status'] = 'cancelled'; self.save(job)
            elif job['status'] == 'running': raise ValueError('Running jobs cannot be interrupted through this bridge.')
            return self.inspect(ident)

def make_handler(bridge):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'LocalBridge'
        sys_version = ''
        def setup(self):
            super().setup(); self.connection.settimeout(90)
        def log_message(self, fmt, *args): pass  # No tokens, prompts or filenames in request logs.
        def send_json(self, status, value):
            if getattr(self, 'reply_started', False): self.close_connection = True; return
            self.reply_started = True
            value = remote_json(value, resources=urllib.parse.urlsplit(self.path).path.startswith('/v1/tripo/'))
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(data)
        def authorized(self):
            expected = 'Bearer ' + bridge.config['token']
            return (self.client_address[0] in bridge.config['allowed_peers'] and not self.headers.get('Origin') and
                    hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode()))
        def body(self):
            if self.headers.get('Transfer-Encoding'): raise ValueError('Chunked uploads are not supported.')
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > MAX_BODY: raise ValueError('Request is too large.')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': raise ValueError('Expected JSON.')
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict): raise ValueError('Expected a JSON object.')
            return value
        def handle_request(self):
            self.reply_started = False
            if not self.authorized():
                self.close_connection = True; return self.send_json(403, {'error': 'Access denied.'})
            route = urllib.parse.urlsplit(self.path).path
            try:
                if self.command == 'GET' and route == '/v1/status':
                    try: backend = bridge.adapters['comfyui.workflow'].status()
                    except ValueError: backend = {'online': False, 'error': 'Local workflow service unavailable.'}
                    backend = {k: backend[k] for k in ('online', 'running', 'pending', 'error') if k in backend}
                    return self.send_json(200, {'bridge': 'local-gpu-bridge', 'adapters': [{'kind': 'comfyui.workflow', **backend}], 'workflow_count': len(bridge.catalog())})
                if self.command == 'GET' and route == '/v1/workflows': return self.send_json(200, {'workflows': bridge.catalog()})
                if route.startswith('/v1/native'):
                    native=bridge.native
                    if self.command=='GET' and route=='/v1/native/status':return self.send_json(200,native.status())
                    if self.command=='GET' and route=='/v1/native/projects':return self.send_json(200,{'projects':native.projects()})
                    if self.command=='POST' and route=='/v1/native/git':return self.send_json(200,native.project_git(**self.body()))
                    if self.command=='POST' and route=='/v1/native/files':return self.send_json(200,native.files(**self.body()))
                    if self.command=='POST' and route=='/v1/native/read':return self.send_json(200,native.read_file(**self.body()))
                    if self.command=='POST' and route=='/v1/native/sync/plan':return self.send_json(201,native.sync_plan(self.body()))
                    if self.command=='POST' and route=='/v1/native/sync/chunk':return self.send_json(200,native.upload_chunk(self.body()))
                    if self.command=='POST' and route=='/v1/native/sync/apply':return self.send_json(200,native.apply_sync(self.body().get('plan_id')))
                    if self.command=='POST' and route=='/v1/native/jobs':return self.send_json(201,native.queue(self.body()))
                    if self.command=='GET' and route=='/v1/native/project-file':
                        query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                        file=native.project_download(query.get('project_id',[''])[0],query.get('path',[''])[0]);size=file.stat().st_size
                        self.reply_started=True;self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(size));self.end_headers()
                        with file.open('rb') as source:shutil.copyfileobj(source,self.wfile,1024*1024)
                        return
                    match=re.fullmatch(r'/v1/native/jobs/([a-f0-9]{32})',route)
                    if self.command=='GET' and match:return self.send_json(200,native.job_status(match[1]))
                    match=re.fullmatch(r'/v1/native/artifacts/([a-f0-9]{32})/(\d{1,4})',route)
                    if self.command=='GET' and match:
                        file=native.artifact(match[1],int(match[2]));size=file.stat().st_size
                        if size>bridge.config.get('max_artifact_bytes',2*1024**3):raise ValueError('Artifact exceeds transfer limit.')
                        self.reply_started=True;self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(size));self.end_headers()
                        with file.open('rb') as source:shutil.copyfileobj(source,self.wfile,1024*1024)
                        return
                if self.command == 'GET' and route == '/v1/vroid/tools': return self.send_json(200, bridge.native.vroid.tools())
                if self.command == 'POST' and route == '/v1/vroid/call': return self.send_json(200, bridge.native.vroid.call(**self.body()))
                if self.command == 'POST' and route == '/v1/unity/start': return self.send_json(200, bridge.native.unity.start(**self.body()))
                if self.command == 'POST' and route == '/v1/unity/stop': return self.send_json(200, bridge.native.unity.stop(**self.body()))
                if self.command == 'POST' and route == '/v1/unity/tools': return self.send_json(200, bridge.native.unity.tools(**self.body()))
                if self.command == 'POST' and route == '/v1/unity/call': return self.send_json(200, bridge.native.unity.call(**self.body()))
                if self.command == 'GET' and route == '/v1/tripo/status': return self.send_json(200, bridge.tripo.status())
                if self.command == 'GET' and route == '/v1/tripo/tools': return self.send_json(200, bridge.tripo.tools())
                if self.command == 'POST' and route == '/v1/tripo/call': return self.send_json(200, bridge.tripo.call(**self.body()))
                if self.command == 'POST' and route == '/v1/tripo/upload': return self.send_json(201, bridge.tripo.upload(**self.body()))
                if self.command == 'GET' and route == '/v1/tripo/file':
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    file = bridge.tripo.file(query.get('path', [''])[0]); size = file.stat().st_size
                    if size > bridge.config.get('max_artifact_bytes', 2*1024**3): raise ValueError('Tripo file exceeds transfer limit.')
                    self.reply_started = True; self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Length', str(size)); self.end_headers()
                    with file.open('rb') as source: shutil.copyfileobj(source, self.wfile, 1024*1024)
                    return
                if self.command == 'GET' and route == '/v1/jobs':
                    with bridge.lock: values = [bridge.public(j) for j in sorted(bridge.jobs.values(), key=lambda j:j['created_at'], reverse=True)[:100]]
                    return self.send_json(200, {'jobs': values})
                if self.command == 'POST' and route == '/v1/jobs': return self.send_json(201, bridge.submit(self.body()))
                match = re.fullmatch(r'/v1/jobs/([a-f0-9]{32})(/cancel)?', route)
                if match:
                    if self.command == 'GET' and not match[2]: return self.send_json(200, bridge.inspect(match[1]))
                    if self.command == 'POST' and match[2]: self.body(); return self.send_json(200, bridge.cancel(match[1]))
                match = re.fullmatch(r'/v1/artifacts/([a-f0-9]{32})/(\d{1,4})', route)
                if self.command == 'GET' and match:
                    bridge.inspect(match[1]); job = bridge.jobs[match[1]]; index = int(match[2])
                    if job['status'] != 'succeeded' or index >= len(job['artifacts']): raise ValueError('Artifact is not available.')
                    with bridge.adapters[job['kind']].artifact(job['artifacts'][index]) as source:
                        size = int(source.headers.get('Content-Length', '-1'))
                        if size < 0 or size > bridge.config.get('max_artifact_bytes', 2*1024**3): raise ValueError('Artifact has an invalid or excessive size.')
                        self.reply_started = True
                        self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Length', str(size))
                        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers()
                        left = size
                        while left:
                            chunk = source.read(min(left, 1024*1024))
                            if not chunk: raise ValueError('Artifact download was interrupted.')
                            self.wfile.write(chunk); left -= len(chunk)
                    return
                if self.command == 'POST' and route == '/v1/assets':
                    body = self.body(); name = body.get('filename', '')
                    extensions = {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.mp4','.mov','.webm','.wav','.mp3','.flac','.glb','.gltf','.obj','.ply'}
                    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name) or name.startswith('.') or pathlib.Path(name).suffix.lower() not in extensions: raise ValueError('Unsupported asset filename.')
                    content = base64.b64decode(body['content_base64'], validate=True)
                    if len(content) > 32*1024**2: raise ValueError('Asset exceeds 32 MB.')
                    return self.send_json(201, bridge.adapters['comfyui.workflow'].upload(name, content))
                return self.send_json(404, {'error': 'Unknown route.'})
            except (ValueError, KeyError, TypeError, urllib.error.URLError) as error:
                self.close_connection = True
                return self.send_json(400, {'error': str(error)[:2000]})
            except (BrokenPipeError, ConnectionResetError, TimeoutError): self.close_connection = True
            except Exception:
                logging.exception('Bridge request failed')
                self.close_connection = True; self.send_json(500, {'error': 'Local bridge error. Check the local bridge log.'})
        do_GET = handle_request
        do_POST = handle_request
    return Handler

class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != 'nt'
    def handle_error(self, request, client_address): logging.error('Client connection ended unexpectedly')

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True); args = parser.parse_args()
    config = json.loads(pathlib.Path(args.config).read_text(encoding='utf-8'))
    config['_config_file']=str(pathlib.Path(args.config).resolve())
    import ipaddress
    if ipaddress.ip_address(config['listen']) not in ipaddress.ip_network('100.64.0.0/10') and config['listen'] != '127.0.0.1': raise ValueError('Only loopback or Tailscale listen addresses are supported.')
    if len(config['token']) < 32: raise ValueError('Bridge token must have at least 32 characters.')
    root = pathlib.Path(config['data_dir']); root.mkdir(parents=True, exist_ok=True)
    acquire_instance_lock(root)
    handler = logging.handlers.RotatingFileHandler(root/'bridge.log', maxBytes=1024*1024, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    # At login Tailscale may not have its address yet. Retry binding without changing VPN settings.
    bridge = Bridge(config); server = None
    for attempt in range(120):
        try: server = Server((config['listen'], config['port']), make_handler(bridge)); break
        except OSError as error:
            if getattr(error, 'winerror', None) == 10048 or getattr(error, 'errno', None) == 98: raise  # Another instance owns the port.
            time.sleep(2)
    if not server: raise RuntimeError('Tailscale address is unavailable.')
    atomic_json(root/'process.json', {'pid': os.getpid(), 'started_at': time.time()})
    logging.info('Local GPU bridge is ready on its configured private address')
    from admin import start_admin
    start_admin(bridge, config.get('admin_port', 18773))
    from comfy_startup import start_background
    start_background(config)
    if config.get('auto_setup_privacy',True) and os.name=='nt':bridge.native.setup_privacy()
    server.serve_forever()

if __name__ == '__main__': main()
