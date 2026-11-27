"""Project-pinned Unity Editor + official CLI MCP, behind the existing private bridge."""
import json
import logging
import os
import pathlib
import re
import subprocess
import threading
import uuid
import urllib.request
from collections import Counter
from contextlib import contextmanager
from native_unity_commands import TOOLS as QUALIFIED_TOOLS, BY_NAME, invoke
from native_control import inside

# No general shell, C# eval, machine diagnostics, account management, or desktop fallback.
EXCLUDED = 'exec,script.eval,script.eval_file,system.*,environment.*,network.*,auth.*,account.*,license.*,desktop.*'
DENIED = re.compile(r'(?:^|[._ /-])(?:exec|shell|eval|eval_file|environment|system|network|auth|account|license|desktop)(?:$|[._ /-])', re.I)
DENIED_NAMES = {'batch', 'invoke_menu', 'run_audit', 'resolve'}
CAPTURE_PATHS = {'game_view':'save_path', 'scene_view':'save_path', 'screenshot':'output',
                 'editor_element':'output', 'runtime_element':'output'}


def capture_path(root, requested, *, asset_relative=False):
    relative = requested if requested not in (None, '') else 'Assets/Screenshots/' + uuid.uuid4().hex + '.png'
    if asset_relative:
        inside(root, relative)
        if relative.split('/')[0] not in ('Assets', 'Packages'):
            relative = 'Assets/' + relative
    path = inside(root, relative)
    startup_path(root, relative)
    if path.suffix.lower() != '.png':
        raise ValueError('Use a project-relative PNG output path.')
    return path


def startup_path(root, relative):
    """Internal startup paths include Temp, which the remote file API forbids."""
    path = root / relative
    for part in (path, *path.parents):
        if part == root: break
        if part.is_symlink() or (part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Unity startup paths must not contain links or reparse points.')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unity startup path is outside the project.')
    return path


@contextmanager
def startup_lock(root):
    """Do not move scene backups belonging to an already open Editor."""
    path = startup_path(root, 'Temp/UnityLockfile')
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = create(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ValueError('Unity project is locked or inaccessible. Close its existing Editor before starting it.')
        try: yield
        finally: close(handle)
    else:
        import fcntl
        with path.open('a+b') as file:
            try: fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('Unity project is locked. Close its existing Editor before starting it.') from None
            try: yield
            finally: fcntl.flock(file, fcntl.LOCK_UN)


def preserve_scene_backups(root):
    """Equivalent to preserving recovery scenes, before Pipeline can start.

    Move the whole directory atomically on the project volume; never delete or
    overwrite scene data, and never touch a project whose Editor holds its lock.
    """
    with startup_lock(root):
        source = startup_path(root, 'Temp/__Backupscenes')
        if not source.is_dir(): return 0
        files = list(source.rglob('*'))
        for file in files: startup_path(root, file.relative_to(root))
        backups = [file.relative_to(source) for file in files if file.is_file() and file.suffix == '.backup']
        if not backups: return 0
        parent = startup_path(root, 'Assets/_Recovery')
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / ('bridge-' + uuid.uuid4().hex)
        source.rename(target)
        for relative in backups:
            file = target / relative
            destination = file.with_suffix('.unity')
            if not destination.exists(): file.rename(destination)
        return len(backups)


class UnityControl:
    def __init__(self, native, session_dir=None):
        self.session_dir = session_dir
        self.native = native
        self.editor = None
        self.editor_project = None
        self.rpc_process = None
        self.pipeline_ready = False
        self.pending = {}
        self.next_id = 0
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.recovery_requests = {}

    def settings(self): return self.native.config.get('native', {})

    def environment(self):
        settings = self.settings()
        data = pathlib.Path(settings.get('unity_data_dir') or self.native.root / 'unity')
        env = {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in
            ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'API_KEY', 'CLAUDE_', 'ORCA_'))}
        for key, folder in [('TEMP','temp'),('TMP','temp'),('UPM_CACHE_ROOT','upm'),('ASSETSTORE_CACHE_PATH','assets')]:
            target = (self.session_dir if folder=='temp' and self.session_dir else data) / folder; target.mkdir(parents=True, exist_ok=True); env[key] = str(target)
        env.update(TZ='UTC', UNITY_NO_CONSENT_PROMPT='1', UNITY_NO_CRASH_REPORT='1',
            UNITY_NO_AGENT_HINTS='1', UNITY_NO_AUTH_BROKER='1', UNITY_NO_EDITOR_IDENTITY_SERVER='1')
        env.pop('UNITY_MCP_DESKTOP_FALLBACK', None)
        return env

    def project(self, project_id):
        project, root = self.native.project(project_id)
        relative = project.get('unity_subdir', '')
        root = inside(root, relative) if relative else root
        if not all((root / part).is_dir() for part in ('Assets','Packages','ProjectSettings')):
            raise ValueError('The approved project is not a Unity project. Configure its Unity subfolder locally.')
        return project, root

    def status(self):
        settings = self.settings()
        installed = bool(settings.get('unity_executable')) and pathlib.Path(settings['unity_executable']).is_file()
        cli = bool(settings.get('unity_cli_executable')) and pathlib.Path(settings['unity_cli_executable']).is_file()
        return {'engine':'unity','installed':installed,'cli_installed':cli,
            'network_isolated': bool(installed and cli and self.native.guard.ready('unity') and self.native.guard.ready('unity-cli')),
            'running': bool(self.editor and self.editor.poll() is None),
            'connected': bool(self.editor and self.editor.poll() is None and self.pipeline_ready
                              and self.rpc_process and self.rpc_process.poll() is None)}

    def editor_state(self, project_id):
        """Background Pipeline health, independent of a blocked MCP/main-thread call."""
        _, root = self.project(project_id)
        editor = self.editor
        if not editor or editor.poll() is not None or self.editor_project != project_id:
            return {'running':False,'ready':False,'state':'not_running'}
        result={'running':True,'ready':False,'state':'unreachable','automated':None,
                'dialog_detection':'pipeline_only'}
        try:
            descriptor=startup_path(root,'Library/Pipeline/.unity-pipeline-port')
            if descriptor.stat().st_size>65536: return result
            data=json.loads(descriptor.read_text(encoding='utf-8'))
            # A stale/foreign descriptor must never redirect a credential-bearing probe.
            if data.get('pid')!=editor.process.pid or pathlib.Path(data.get('projectPath','')).resolve()!=root.resolve():
                return result
            port=data.get('port');token=data.get('evalToken')
            if type(port)is not int or not 1<=port<=65535 or not isinstance(token,str) or not token or len(token)>4096:
                return result
            result['automated']=data.get('mode')=='batchmode' or not bool(data.get('info'))
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):return None
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            req=urllib.request.Request('http://127.0.0.1:'+str(port)+'/api/status',headers={'Authorization':'Bearer '+token})
            with opener.open(req,timeout=3) as response:
                raw=response.read(65537)
            if len(raw)>65536:return result
            value=json.loads(raw)
            state=value.get('status')
            if state not in ('ready','settling','blocked_by_dialog','compiling','reloading','error'):state='unavailable'
            result.update(state=state,ready=state=='ready')
            if isinstance(value.get('dialog'),dict):
                from native_control import private_result
                result['dialog']=private_result({k:value['dialog'][k] for k in ('title','message','buttons') if k in value['dialog']})
            # Older Editors and OS file pickers are outside Pipeline's dialog coverage.
            if result['automated'] is False:
                result['next']='Restart with unity_recover(discard_changes=true) after saving any wanted edits to enable automated mode. Pipeline may miss native dialogs.'
            elif state=='blocked_by_dialog':
                result['next']='Inspect the dialog; unity_recover(discard_changes=true) restarts only this managed Editor. It does not click dialogs or retry edits.'
        except (OSError,ValueError,AttributeError):pass
        return result

    def recover(self, project_id, discard_changes=False, request_id=None):
        if discard_changes is not True:
            raise ValueError('Recovery discards unsaved Unity changes. Save first or explicitly set discard_changes=true.')
        if not isinstance(request_id,str) or not re.fullmatch('[a-f0-9]{32}',request_id):
            raise ValueError('Provide a 32-character request_id; reuse it after uncertain recovery responses.')
        self.project(project_id)
        if not self.lock.acquire(timeout=2):
            raise ValueError('A Unity request is still in flight. Wait for it to finish or time out, then retry recovery; no editor was stopped.')
        try:
            previous=self.recovery_requests.get(request_id)
            if previous:
                if previous['project_id']!=project_id:raise ValueError('Recovery request_id belongs to a different project.')
                if previous.get('error'):raise ValueError('This recovery attempt failed; inspect state before using a new request_id.')
                return {**previous,'already_requested':True}
            if self.editor_project not in (None,project_id):raise ValueError('This is not the managed Unity project.')
            self.native.guard.require('unity');self.native.guard.require('unity-cli')
            self.recovery_requests[request_id]={'project_id':project_id,'error':True}
            self.stop(project_id)
            result={**self.start(project_id),'restarted':True,'automated':True,'edits_retried':False}
            self.recovery_requests[request_id]=result
            return result
        finally:self.lock.release()

    def start(self, project_id):
        with self.lock:
            project, root = self.project(project_id)
            self.native.guard.require('unity'); self.native.guard.require('unity-cli')
            if self.editor and self.editor.poll() is None:
                if self.editor_project != project_id: raise ValueError('Stop the managed Unity Editor before switching projects.')
                return {'started':True,'project_id':project_id,'already_running':True}
            if self.editor: self.editor.close(); self.editor = None
            self.close_rpc()
            with startup_lock(root):
                if project.get('git',{}).get('enabled') and project['git'].get('auto_pull_before_render'):
                    from native_git import git_for
                    _, repository = self.native.project(project_id)
                    git_for(self.native, project, repository).pull(uuid.uuid4().hex)
                    # Revalidate the editor directory after updating a nested project.
                    self.project(project_id)
            log = (self.session_dir or pathlib.Path(self.settings().get('unity_data_dir') or self.native.root/'unity'))/'editor.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            recovered = preserve_scene_backups(root)
            # Unity needs shader/compiler/package-manager children. The parent and
            # children are killed together when this bounded Windows job closes.
            args = [self.settings()['unity_executable'], '-projectPath', str(root), '-automated', '-logFile', str(log), '-force-d3d11', '-job-worker-count', '4']
            self.editor = self.native.process_factory(args, root, log, self.environment(), show_window=True, process_limit=128)
            self.editor_project = project_id
            return {'started':True,'project_id':project_id,'ready':False,'automated':True,
                'recovered_scenes':recovered,
                'next':'Wait for project import, then call unity_tools. No desktop screenshot fallback is enabled.'}

    def stop(self, project_id):
        with self.lock:
            self.native.project(project_id)
            if self.editor_project not in (None, project_id): raise ValueError('This is not the managed Unity project.')
            self.close_rpc()
            if self.editor: self.editor.stop(); self.editor.close()
            self.editor = None; self.editor_project = None
            return {'stopped':True}

    def close_rpc(self):
        self.pipeline_ready = False
        process, self.rpc_process = self.rpc_process, None
        if process:
            try: process.stdin.close(); process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired): process.kill(); process.wait(timeout=5)
            finally:
                if process.stdout: process.stdout.close()

    def _read(self, process):
        try:
            for line in process.stdout:
                try: reply = json.loads(line)
                except (ValueError, UnicodeError): continue
                slot = self.pending.get(reply.get('id'))
                if slot: slot['value'] = reply; slot['event'].set()
        finally:
            for slot in list(self.pending.values()):
                if slot['process'] is process: slot['event'].set()

    def _send(self, method, params=None, notify=False):
        with self.write_lock:
            self.next_id += 1; ident = self.next_id
            slot = {'event':threading.Event(),'value':None,'process':self.rpc_process}
            if not notify: self.pending[ident] = slot
            request = {'jsonrpc':'2.0','method':method,'params':params or {}}
            if not notify: request['id'] = ident
            try:
                self.rpc_process.stdin.write((json.dumps(request)+'\n').encode()); self.rpc_process.stdin.flush()
            except (OSError, ValueError):
                self.pending.pop(ident,None)
                raise
        if notify: return {}
        try:
            if not slot['event'].wait(180) or slot['value'] is None:
                raise ValueError('Unity did not answer. Check the local editor before repeating an edit.')
            if 'error' in slot['value']: raise ValueError('Unity rejected the request. Inspect tool parameters and local editor state.')
            return slot['value'].get('result', {})
        finally: self.pending.pop(ident, None)

    def ensure_rpc(self, project_id):
        self.project(project_id)
        if not self.editor or self.editor.poll() is not None or self.editor_project != project_id:
            raise ValueError('Start this approved project with unity_start first. Unmanaged editors are not controlled.')
        self.native.guard.require('unity'); self.native.guard.require('unity-cli')
        if self.rpc_process and self.rpc_process.poll() is None: return
        _, root = self.project(project_id)
        self.rpc_process = subprocess.Popen([self.settings()['unity_cli_executable'],'mcp','--project-path',str(root),
            '--exclude-tools',EXCLUDED], cwd=root, env=self.environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000 if os.name=='nt' else 0)
        threading.Thread(target=self._read,args=(self.rpc_process,),daemon=True).start()
        self._send('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'orca-toolkit','version':'1'}})
        self._send('notifications/initialized',notify=True)

    def tools(self, project_id):
        with self.lock:
            self.pipeline_ready = False
            self.ensure_rpc(project_id)
            tools = []
            catalog = self._send('tools/list').get('tools', [])
            counts = Counter(entry.get('name','') for entry in catalog)
            for entry in catalog:
                name = entry.get('name','')
                # Some CLI releases flatten command groups to duplicate names.
                # Never route an ambiguous "run" to a different command group.
                if counts[name] != 1 or DENIED.search(name) or name in DENIED_NAMES: continue
                if name in CAPTURE_PATHS:
                    props = dict(entry.get('inputSchema', {}).get('properties', {}))
                    if CAPTURE_PATHS[name] not in props: continue
                    props.pop('include_inline_image', None)
                    props.pop('max_resolution', None)
                    props[CAPTURE_PATHS[name]] = {'type':'string','description':'Optional project-relative PNG output path.'}
                    entry = {**entry, 'description':f'Capture {name} to a project PNG. Fetch the returned path with download_project_file.',
                             'inputSchema':{**entry['inputSchema'], 'properties':props}}
                tools.append({k:entry[k] for k in ('name','description','inputSchema') if k in entry})
            self.pipeline_ready = any(entry['name'] != 'unity-cli-status' for entry in tools)
            exposed = tools + QUALIFIED_TOOLS
            if project_id.startswith('scratch.'):
                # Standalone workspaces may capture and inspect their editor without installing executable packages.
                standalone = set(CAPTURE_PATHS) | {'console.get','console.status','test.list','unity-cli-status'}
                exposed = [entry for entry in exposed if entry['name'] in standalone]
            return {'tools':exposed, 'ready':self.pipeline_ready}

    def capture(self, project_id, name, arguments):
        project, root = self.project(project_id)
        key = CAPTURE_PATHS[name]
        path = capture_path(root, arguments.get(key), asset_relative=key == 'save_path')
        relative = path.relative_to(root).as_posix()
        output = str(path) if name == 'runtime_element' else relative
        args = {**arguments, key:output}
        if key == 'save_path':
            args['include_inline_image'] = False
        previous = path.stat() if path.exists() else None
        reply = self._send('tools/call', {'name':name, 'arguments':args})
        if reply.get('isError') or not inside(root,relative).is_file():
            raise ValueError('Unity did not write the screenshot. Check the selected view and Editor state.')
        current = path.stat()
        if previous and (current.st_mtime_ns,current.st_size) == (previous.st_mtime_ns,previous.st_size):
            raise ValueError('Unity did not update the requested PNG.')
        with path.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            raise ValueError('Unity returned an invalid PNG.')
        download = pathlib.PurePosixPath(project.get('unity_subdir') or '') / relative
        return {'project_id':project_id, 'path':download.as_posix(), 'bytes':current.st_size,
                'width':int.from_bytes(header[16:20], 'big'), 'height':int.from_bytes(header[20:24], 'big')}

    def call(self, project_id, name, arguments=None):
        if not isinstance(name,str) or DENIED.search(name) or name in DENIED_NAMES: raise ValueError('This Unity tool is not exposed.')
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments,dict) or len(json.dumps(arguments))>65536: raise ValueError('Unity arguments must be an object under 64 KB.')
        if self.editor_state(project_id).get('state')=='blocked_by_dialog':
            raise ValueError('Unity is blocked by a dialog. Read unity_editor_state; save wanted changes before unity_recover(discard_changes=true). The edit was not submitted.')
        with self.lock:
            exposed = {tool['name'] for tool in self.tools(project_id)['tools']}
            if name not in exposed: raise ValueError('Read unity_tools and use an exposed tool name.')
            if name in BY_NAME: return invoke(self, project_id, name, arguments)
            try:
                if name in CAPTURE_PATHS: return self.capture(project_id, name, arguments)
                if name == 'wait' and arguments.get('on_met'):
                    action = arguments['on_met']
                    if isinstance(action, str): action = json.loads(action)
                    if not isinstance(action, dict): raise ValueError('on_met must be an object.')
                    if action.get('capture') is not None:
                        capture = action['capture']
                        if not isinstance(capture, dict): raise ValueError('on_met.capture must be an object.')
                        project, root = self.project(project_id)
                        path = capture_path(root, capture.get('save_path'), asset_relative=True).relative_to(root).as_posix()
                        action = {**action, 'capture':{**capture, 'save_path':path, 'include_image':False}}
                        args = {**arguments, 'on_met':action}
                        result = self._send('tools/call', {'name':name, 'arguments':args})
                        return {**result, 'capture_path':(pathlib.PurePosixPath(project.get('unity_subdir') or '') / path).as_posix()}
                return self._send('tools/call',{'name':name,'arguments':arguments})
            except (OSError, BrokenPipeError):
                logging.exception('Unity MCP transport stopped')
                raise ValueError('Unity connection stopped. Inspect editor state; edits are never retried automatically.') from None


class UnityProjects:
    def __init__(self, native):
        self.native = native
        self.base = UnityControl(native)
        self.sessions = {}

    def session(self, ident):
        import hashlib
        project, root = self.base.project(ident)
        with self.native.lock:
            if root not in self.sessions:
                data = pathlib.Path(self.base.settings().get('unity_data_dir') or self.native.root/'unity')
                directory = data/'projects'/hashlib.sha256(str(root).encode()).hexdigest()
                self.sessions[root] = UnityControl(self.native, directory)
            return self.sessions[root]

    def status(self):
        result = self.base.status()
        with self.native.lock:
            editors = [s for s in self.sessions.values() if (editor := s.editor) and editor.poll() is None]
            result.update(running=bool(editors), connected=any(s.pipeline_ready and (rpc := s.rpc_process)
                           and rpc.poll() is None for s in editors))
        return result

    def reap(self):
        with self.native.lock:
            sessions = tuple(self.sessions.values())
        for session in sessions:
            if not session.lock.acquire(blocking=False):
                continue
            try:
                editor = session.editor
                if editor is not None and editor.poll() is not None:
                    session.editor = None
                    session.editor_project = None
                    try:
                        session.close_rpc()
                    finally:
                        editor.close()
            finally:
                session.lock.release()

    def editor_state(self, project_id):
        return self.session(project_id).editor_state(project_id)

    def dispatch(self, project_id, method, *args):
        launching = method in ('start','recover')
        with self.native.operation(project_id,'unity' if launching else None,
                                   busy_timeout=2 if method=='recover' else 180) as (_,root):
            session = self.session(project_id)
            try:
                return getattr(session,method)(project_id,*args)
            finally:
                if launching and session.editor_project == project_id and session.editor is not None:
                    self.native.capacity.track(('unity',root,project_id),session.editor)

    def start(self, project_id):
        return self.dispatch(project_id,'start')

    def stop(self, project_id):
        return self.dispatch(project_id,'stop')

    def recover(self, project_id, discard_changes=False, request_id=None):
        return self.dispatch(project_id,'recover',discard_changes,request_id)

    def tools(self, project_id):
        return self.dispatch(project_id,'tools')

    def call(self, project_id, name, arguments=None):
        return self.dispatch(project_id,'call',name,arguments)
