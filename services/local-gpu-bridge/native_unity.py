"""Project-pinned Unity Editor + official CLI MCP, behind the existing private bridge."""
import json
import logging
import os
import pathlib
import re
import subprocess
import threading
from collections import Counter
from native_control import inside

# No general shell, C# eval, machine diagnostics, account management, or desktop fallback.
EXCLUDED = 'exec,script.eval,script.eval_file,system.*,environment.*,network.*,auth.*,account.*,license.*,desktop.*'
DENIED = re.compile(r'(?:^|[._ /-])(?:exec|shell|eval|eval_file|environment|system|network|auth|account|license|desktop)(?:$|[._ /-])', re.I)
DENIED_NAMES = {'batch', 'invoke_menu', 'run_audit', 'resolve'}


class UnityControl:
    def __init__(self, native):
        self.native = native
        self.editor = None
        self.editor_project = None
        self.rpc_process = None
        self.pending = {}
        self.next_id = 0
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()

    def settings(self): return self.native.config.get('native', {})

    def environment(self):
        settings = self.settings()
        data = pathlib.Path(settings.get('unity_data_dir') or self.native.root / 'unity')
        env = {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in
            ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'API_KEY', 'CLAUDE_', 'ORCA_'))}
        for key, folder in [('TEMP','temp'),('TMP','temp'),('UPM_CACHE_ROOT','upm'),('ASSETSTORE_CACHE_PATH','assets')]:
            target = data / folder; target.mkdir(parents=True, exist_ok=True); env[key] = str(target)
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
            'connected': bool(self.editor and self.editor.poll() is None)}

    def start(self, project_id):
        with self.lock:
            project, root = self.project(project_id)
            self.native.guard.require('unity'); self.native.guard.require('unity-cli')
            if self.editor and self.editor.poll() is None:
                if self.editor_project != project_id: raise ValueError('Stop the managed Unity Editor before switching projects.')
                return {'started':True,'project_id':project_id,'already_running':True}
            if self.editor: self.editor.close(); self.editor = None
            if project.get('git',{}).get('enabled') and project['git'].get('auto_pull_before_render'):
                from native_git import git_for
                git_for(self.native, project, root).pull(__import__('uuid').uuid4().hex)
            log = pathlib.Path(self.settings().get('unity_data_dir') or self.native.root/'unity')/'editor.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            # Unity needs shader/compiler/package-manager children. The parent and
            # children are killed together when this bounded Windows job closes.
            args = [self.settings()['unity_executable'], '-projectPath', str(root), '-logFile', str(log), '-force-d3d11', '-job-worker-count', '4']
            self.editor = self.native.process_factory(args, root, log, self.environment(), show_window=True, process_limit=128)
            self.editor_project = project_id
            return {'started':True,'project_id':project_id,'ready':False,
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
            for slot in list(self.pending.values()): slot['event'].set()

    def _send(self, method, params=None, notify=False):
        with self.write_lock:
            self.next_id += 1; ident = self.next_id
            slot = {'event':threading.Event(),'value':None}
            if not notify: self.pending[ident] = slot
            request = {'jsonrpc':'2.0','method':method,'params':params or {}}
            if not notify: request['id'] = ident
            self.rpc_process.stdin.write((json.dumps(request)+'\n').encode()); self.rpc_process.stdin.flush()
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
            self.ensure_rpc(project_id)
            tools = []
            catalog = self._send('tools/list').get('tools', [])
            counts = Counter(entry.get('name','') for entry in catalog)
            for entry in catalog:
                name = entry.get('name','')
                # Some CLI releases flatten command groups to duplicate names.
                # Never route an ambiguous "run" to a different command group.
                if counts[name] != 1 or DENIED.search(name) or name in DENIED_NAMES: continue
                tools.append({k:entry[k] for k in ('name','description','inputSchema') if k in entry})
            return {'tools':tools}

    def call(self, project_id, name, arguments=None):
        if not isinstance(name,str) or DENIED.search(name) or name in DENIED_NAMES: raise ValueError('This Unity tool is not exposed.')
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments,dict) or len(json.dumps(arguments))>65536: raise ValueError('Unity arguments must be an object under 64 KB.')
        with self.lock:
            exposed = {tool['name'] for tool in self.tools(project_id)['tools']}
            if name not in exposed: raise ValueError('Read unity_tools and use an exposed tool name.')
            try: return self._send('tools/call',{'name':name,'arguments':arguments})
            except (OSError, BrokenPipeError):
                logging.exception('Unity MCP transport stopped')
                raise ValueError('Unity connection stopped. Inspect editor state; edits are never retried automatically.') from None
