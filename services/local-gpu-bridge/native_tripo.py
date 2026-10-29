"""Tripo Studio through the user's own Studio account (Ador-able/tripo-studio-mcp).

The account, its dedicated browser profile and any saved credential stay on this computer; the VPS
sees only the plugin's workflow tools. Local files cross the bridge as tripo:<root>/<relative>
handles, never as Windows paths. The China site (studio.tripo3d.com) serves the same Studio API on
other hosts, so region "cn" runs a copy of the plugin with its site addresses and loopback port
changed, with its own data directory, browser profile and debug port.
"""
import base64, datetime, hashlib, json, logging, os, pathlib, re, shutil, socket, subprocess, threading, time, uuid

HOME = pathlib.Path(os.environ.get('USERPROFILE') or pathlib.Path.home())
LOCAL = pathlib.Path(os.environ.get('LOCALAPPDATA') or HOME / 'AppData/Local')
PLUGIN_CACHE = LOCAL / 'LocalGpuBridge/tripo/plugins'
REGIONS = {
    'global': {'studio': 'https://studio.tripo3d.ai', 'api': 'https://api.tripo3d.ai', 'account': 'https://www.tripo3d.ai',
               'port': 32175, 'cdp': 9222, 'data': 'TripoStudioMCP'},
    'cn': {'studio': 'https://studio.tripo3d.com', 'api': 'https://api-cn.tripo3d.com', 'account': 'https://www.tripo3d.com',
           'port': 32176, 'cdp': 9223, 'data': 'TripoStudioMCP-cn'},
}
PATCH_VERSION = 5
SCHEDULER_PATCHES = [
    ('var MAX_CONCURRENCY = 10;', 'var MAX_CONCURRENCY = 3;'),
    ('current.consecutive_accepted += 1;', 'current.consecutive_accepted = Math.min(5, current.consecutive_accepted + 1);'),
    ('current.consecutive_congestion += 1;', 'current.consecutive_congestion = Math.min(1000, current.consecutive_congestion + 1);'),
    ('return clone8(document2.accounts[accountFingerprint] ?? defaultSchedulerState());',
     'return clone8({ ...(document2.accounts[accountFingerprint] ?? defaultSchedulerState()), concurrency_limit: 3 });'),
    ('const state2 = clone8(document2.accounts[accountFingerprint] ?? defaultSchedulerState());',
     'const state2 = clone8(document2.accounts[accountFingerprint] ?? defaultSchedulerState()); state2.concurrency_limit = 3;'),
]
UPLOAD_CLIENT = '            useAccelerateEndpoint: transport.useAccelerateEndpoint'
CN_UPLOAD_CLIENT = UPLOAD_CLIENT + ''',
            ...(() => {
              const host = String(token.host ?? "").replace(/^https:\\/\\//, "").replace(/\\/$/, "");
              const match = /^s3\\.(bj|gz|su|bd|fwh|hkg|cd|fsh)\\.bcebos\\.com$/.exec(host);
              if (!match) throw new TripoError("REMOTE_SCHEMA_CHANGED", "China-site storage returned an unsupported endpoint.", { stage: "upload" });
              return { endpoint: "https://" + host, region: match[1], forcePathStyle: true, useAccelerateEndpoint: false };
            })()'''
ACTION_READ = '''    const binding = await this.#index.get(actionId);
    return await this.#publicAction(binding, await this.#backendSnapshot(binding));'''
RECOVER_ACTION_READ = '''    const binding = await this.#index.get(actionId);
    const snapshot = await this.#backendSnapshot(binding);
    if (["submitted", "queued", "running"].includes(snapshot.status) && this.#ownsBindingAccount(binding)) this.#observe(binding);
    return await this.#publicAction(binding, snapshot);'''
# Credentials, account switching and the local gallery never cross the bridge.
HIDDEN = {'tripo_set_account', 'tripo_clear_account', 'tripo_open_gallery'}
HANDLE = re.compile(r'tripo:(inputs|assets|archive)/([^\x00-\x1f"<>|?*]{1,512})')
UPLOAD_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.glb', '.gltf', '.obj', '.fbx', '.stl'}
MARKER = '.tripo-studio-mcp-profile'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
KEEPALIVE_SECONDS = 60
# The VPS sees these English descriptions; the plugin's own text is not forwarded.
TOOL_TEXT = {
    'tripo_get_status': 'Show the Studio sign-in state, the credit balance and the background workflow queue.',
    'tripo_list_models': 'List Studio models by scope and category, page by page.',
    'tripo_get_model': 'Read one model: parts, capabilities, animation presets and preview images.',
    'tripo_list_images': 'List Studio images, page by page.',
    'tripo_get_image': 'Read one Studio image and its outputs; missing result files are downloaded.',
    'tripo_list_templates': 'List the current image templates; optionally preview chosen template ids.',
    'tripo_get_workflow_capabilities': 'List every workflow operation with its JSON Schema, the results it produces, where they plug into later steps, and whether it may spend credits.',
    'tripo_start_workflow': 'Validate, persist and queue a workflow of one or more operation steps. Returns workflow_id at once; it does not wait for the remote tasks.',
    'tripo_get_workflow': 'Read a workflow from the local record: status, results and failure reason.',
    'tripo_list_workflows': 'List workflows from the local record, optionally filtered by status.',
    'tripo_get_workflow_log': 'Read the background event log of a workflow from the last 24 hours.',
    'tripo_cancel_workflow': 'Stop a workflow: steps not yet submitted are dropped; remote cancellation is attempted at a safe point.',
    'tripo_retry_workflow': 'Start a workflow again from its first step under a new workflow_id. This can submit and spend credits again: only on explicit user request.',
}
OPERATION_TEXT = {
    'image.generate': 'Generate Studio images from a prompt, a template or local reference images.',
    'image.multiview': 'Generate four views from one Studio image.',
    'image.regenerate': 'Regenerate an existing Studio image or four-view set.',
    'model.generate': 'Generate one 3D model from text, one image or several views.',
    'model.import': 'Import a local GLB, OBJ, FBX or STL model.',
    'model.segment': 'Split a model into semantic parts.',
    'model.complete_parts': 'Complete chosen parts with AI, or fill their holes.',
    'model.remesh': 'Retopologize chosen model parts.',
    'texture.generate': 'Generate model textures from text, an image or several views.',
    'texture.edit_preview': 'Create a texture edit preview bound to one camera view.',
    'texture.edit_apply': 'Apply a confirmed layered texture edit to the model.',
    'texture.upscale': 'Upscale model textures to a higher resolution.',
    'texture.pbr': 'Generate PBR materials for a textured model.',
    'model.rig': 'Rig a model automatically.',
    'model.animate': 'Retarget a preset animation onto a rigged model.',
}


def ascii_text(value):
    """Drops non-ASCII description/title fields anywhere in a schema."""
    if isinstance(value, list): return [ascii_text(v) for v in value]
    if not isinstance(value, dict): return value
    return {k: ascii_text(v) for k, v in value.items()
            if not (k in ('description', 'title') and isinstance(v, str) and not v.isascii())}


def english_tool(tool):
    tool = ascii_text(tool)
    # Upstream output schemas describe private account/environment fields that
    # this bridge deliberately removes from structured results.
    tool.pop('outputSchema', None)
    tool['description'] = TOOL_TEXT.get(tool.get('name'), tool.get('description') or 'Tripo Studio tool.')
    return tool


def english_capabilities(result):
    def fix(value):
        if not isinstance(value, dict) or not isinstance(value.get('operations'), list): return value
        operations = []
        for op in value['operations']:
            op = ascii_text(op)
            if isinstance(op, dict): op['description'] = OPERATION_TEXT.get(op.get('name'), op.get('description') or '')
            operations.append(op)
        return {**value, 'operations': operations}
    result = dict(result)
    if 'structuredContent' in result: result['structuredContent'] = fix(result['structuredContent'])
    content = []
    for item in result.get('content', []):
        if isinstance(item, dict) and item.get('type') == 'text':
            try: item = {**item, 'text': json.dumps(fix(json.loads(item['text'])), ensure_ascii=False, indent=1)}
            except ValueError: pass
        content.append(item)
    if content: result['content'] = content
    return result


def inside(root, relative):
    target = (root / relative).resolve(); base = root.resolve()
    if target != base and base not in target.parents: raise ValueError('Tripo path leaves its folder.')
    return target


def patches(region):
    """Exact edits for a non-global copy; each old text must occur once in the plugin bundle."""
    if region == 'global': return {}
    site, base = REGIONS[region], REGIONS['global']
    port = (f'var TRIPO_MCP_HTTP_PORT = {base["port"]};', f'var TRIPO_MCP_HTTP_PORT = {site["port"]};')
    host = lambda url: url.split('//', 1)[1]
    return {
        'mcp/server.mjs': SCHEDULER_PATCHES + [(UPLOAD_CLIENT, CN_UPLOAD_CLIENT), (ACTION_READ, RECOVER_ACTION_READ),
                           (f'var STUDIO_ORIGIN = "{base["studio"]}";', f'var STUDIO_ORIGIN = "{site["studio"]}";'),
                           (f'var STUDIO_API_BASE_URL = "{base["api"]}";', f'var STUDIO_API_BASE_URL = "{site["api"]}";'),
                           (f'var TRIPO_ACCOUNT_ORIGIN = "{base["account"]}";', f'var TRIPO_ACCOUNT_ORIGIN = "{site["account"]}";'),
                           (f':{host(base["studio"])}`', f':{host(site["studio"])}`'),
                           ('`tripo-studio-global-server\\0${options2.identity ?? currentUserIdentity()}`',
                            '`orca-tripo-' + region + '-server\\0${process.env.TRIPO_DATA_DIR}\\0${options2.identity ?? currentUserIdentity()}`'),
                           ('session2.status().authenticated || credentialStatus?.state === "available"',
                            'session2.status().authenticated || credentialStatus?.state === "available" || process.env.TRIPO_REUSE_BROWSER_SESSION === "1"'),
                           ('if ((options2.platform ?? process.platform) !== "win32") return new InteractionRequiredCredentialStore();',
                            'if (process.env.TRIPO_COOKIE_ONLY === "1" || (options2.platform ?? process.platform) !== "win32") return new InteractionRequiredCredentialStore();'), port],
        'mcp/bootstrap.mjs': [port],
    }


def pid_alive(pid):
    if os.name != 'nt':
        try: os.kill(pid, 0); return True
        except OSError: return False
    # On Windows os.kill(pid, 0) terminates the process; query it instead.
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle: return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally: kernel.CloseHandle(handle)


def backend_gone(result):
    return isinstance(result, dict) and result.get('isError') and any(
        'could not connect to its local backend' in str(item.get('text', '')) for item in result.get('content', []) if isinstance(item, dict))


def find_browser(configured=None):
    names = [configured] if configured else []
    for base in (os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', ''), str(LOCAL)):
        names += [base + '/Google/Chrome/Application/chrome.exe', base + '/Microsoft/Edge/Application/msedge.exe']
    for name in names:
        if name and pathlib.Path(name).is_file(): return str(pathlib.Path(name))
    raise ValueError('Install Google Chrome or Microsoft Edge for the Tripo login browser.')


class TripoControl:
    def __init__(self, config, command=None):
        settings = config.get('tripo') or {}
        self.region = settings.get('region', 'global')
        if self.region not in REGIONS: raise ValueError('tripo.region must be global or cn.')
        self.site = REGIONS[self.region]
        self.cache = pathlib.Path(settings.get('plugin_cache') or PLUGIN_CACHE)
        self.runtime_dir = pathlib.Path(config.get('data_dir') or LOCAL / 'LocalGpuBridge') / 'tripo' / self.region
        self.data_dir = pathlib.Path(settings.get('data_dir') or LOCAL / self.site['data'])
        self.browser = settings.get('browser')
        assets = pathlib.Path(settings.get('asset_root') or HOME / 'Documents/TripoStudio')
        self.roots = {'inputs': assets / 'bridge-inputs', 'assets': assets, 'archive': self.data_dir / 'archive'}
        self.command = command
        self.process = None; self.lock = threading.Lock(); self.start_lock = threading.Lock()
        self.alias_lock = threading.Lock()
        self.pending = {}; self.next_id = 1

    def plugin_root(self):
        versions = sorted(p for p in self.cache.glob('*') if (p / 'mcp/bootstrap.mjs').is_file())
        if not versions: raise ValueError('Tripo Studio plugin is not installed on the GPU computer.')
        return versions[-1]

    def runtime_root(self):
        source = self.plugin_root(); edits = patches(self.region)
        if not edits: return source
        digest = hashlib.sha256(b''.join((source / name).read_bytes() for name in sorted(edits))).hexdigest()
        target = self.runtime_dir / (source.name + '-bridge' + str(PATCH_VERSION) + '-' + digest[:12]); stamp = target / '.bridge-patch.json'
        try:
            if json.loads(stamp.read_text(encoding='utf-8')) == {'source': digest, 'patch': PATCH_VERSION, 'region': self.region}: return target
        except (OSError, ValueError): pass
        if target.exists():raise ValueError('The managed Tripo runtime failed its stamp check. Refusing to overwrite a possibly active directory.')
        staging = target.with_name(target.name + '.staging')
        if not staging.resolve().is_relative_to(self.runtime_dir.resolve()):raise ValueError('Unsafe Tripo staging path.')
        shutil.rmtree(staging, ignore_errors=True); shutil.copytree(source, staging)
        for name, pairs in edits.items():
            file = staging / name; text = file.read_text(encoding='utf-8')
            for old, new in pairs:
                if text.count(old) != 1:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise ValueError('The Tripo Studio plugin changed its site settings; region ' + self.region + ' needs a bridge update.')
                text = text.replace(old, new)
            file.write_text(text, encoding='utf-8')
        (staging / '.bridge-patch.json').write_text(json.dumps({'source': digest, 'patch': PATCH_VERSION, 'region': self.region}), encoding='utf-8')
        staging.rename(target)
        return target

    def environment(self):
        env = dict(os.environ, TZ='UTC', NODE_USE_ENV_PROXY='1', TRIPO_DATA_DIR=str(self.data_dir), TRIPO_REUSE_BROWSER_SESSION='1',
                   TRIPO_CHROME_CDP_URL=f'http://127.0.0.1:{self.site["cdp"]}')
        if self.region=='cn':env['TRIPO_COOKIE_ONLY']='1'
        # Pin the browser so the dedicated profile is never opened by two different browsers.
        try: env['TRIPO_CHROME_EXECUTABLE'] = find_browser(self.browser)
        except ValueError: pass
        return env

    def _read(self, process):
        for line in process.stdout:
            try: value = json.loads(line)
            except ValueError: continue
            slot = self.pending.get(value.get('id'))
            if slot: slot['value'] = value; slot['event'].set()
        for slot in list(self.pending.values()): slot['event'].set()

    def _send(self, method, params=None, timeout=120, notify=False):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None: message['params'] = params
        with self.lock:
            if notify:
                self.process.stdin.write((json.dumps(message) + '\n').encode()); self.process.stdin.flush(); return None
            ident = self.next_id; self.next_id += 1
            slot = {'event': threading.Event(), 'value': None}; self.pending[ident] = slot
            message['id'] = ident
            self.process.stdin.write((json.dumps(message) + '\n').encode()); self.process.stdin.flush()
        try:
            if not slot['event'].wait(timeout) or slot['value'] is None:
                raise ValueError('Tripo Studio did not answer in time. Query the workflow before repeating a submission.')
        finally: self.pending.pop(ident, None)
        if 'error' in slot['value']: raise ValueError('Tripo Studio rejected the request: ' + str(slot['value']['error'].get('message', ''))[:500])
        return slot['value']['result']

    def ensure_started(self):
        with self.start_lock:
            if self.login_active(): raise ValueError('Tripo Studio sign-in is in progress on the GPU computer. Try again after it finishes.')
            if self.process is not None and self.process.poll() is None: return
            if self.command: command, cwd = self.command, None
            else: command, cwd = ['node', './mcp/bootstrap.mjs'], str(self.runtime_root())
            # The bootstrap keeps the plugin's singleton backend (session, headless browser,
            # workflow ledger) alive for as long as the bridge holds this connection.
            self.process = subprocess.Popen(command, cwd=cwd, env=self.environment(), stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            threading.Thread(target=self._read, args=(self.process,), daemon=True).start()
            self._send('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                      'clientInfo': {'name': 'local-gpu-bridge', 'version': '1'}}, timeout=60)
            self._send('notifications/initialized', notify=True)
            # tools/list is served by the lightweight bootstrap without starting
            # its backend. A read is required to establish the lifetime lease.
            try:
                ready = self._send('tools/call', {'name': 'tripo_get_status', 'arguments': {}}, timeout=60)
                if ready.get('isError') and any(
                    any(s in str(item.get('text','')) for s in ('MCP service is unavailable','MCP version mismatch','could not connect to its local backend'))
                    for item in ready.get('content',[]) if isinstance(item,dict)):
                    raise ValueError('Tripo Studio backend did not become ready. Check the local service log.')
            except Exception:
                process, self.process = self.process, None
                try: process.stdin.close(); process.wait(5)
                except (OSError, subprocess.TimeoutExpired): process.kill()
                raise

    def stop(self):
        with self.start_lock:
            process, self.process = self.process, None
            if process is None or process.poll() is not None: return
            try: process.stdin.close()
            except OSError: pass
            try: process.wait(15)
            except subprocess.TimeoutExpired: process.kill()

    def to_local(self, value):
        if isinstance(value, str):
            match = HANDLE.fullmatch(value)
            return str(inside(self.roots[match[1]], self.resolve_input_alias(match[2]) if match[1] == 'inputs' else match[2])) if match else value
        if isinstance(value, list): return [self.to_local(v) for v in value]
        if isinstance(value, dict): return {k: self.to_local(v) for k, v in value.items()}
        return value

    def to_handles(self, text):
        # Upstream workflows return gallery route IDs, not filesystem paths.
        for route, relative in self.gallery_files().items():
            text = re.sub(re.escape(route) + r'(?=["\\\s]|$)',
                          lambda _: 'tripo:archive/' + relative, text)
        # Results nest JSON in JSON, so a separator may be any run of backslashes; a segment
        # never contains one, which keeps an escaped closing quote (\") out of the path.
        sep = r'(?:\\+|/)'
        for name in ('inputs', 'archive', 'assets'):
            parts = [p for p in re.split(r'[\\/]+', str(self.roots[name].resolve())) if p]
            pattern = sep.join(re.escape(p) for p in parts) + r'(?=[\\/"\s]|$)((?:' + sep + r'[^"\\/\n\r]+)*)'
            text = re.sub(pattern, lambda m: 'tripo:' + name + '/' + '/'.join(p for p in re.split(r'[\\/]+', m[1]) if p),
                          text, flags=re.IGNORECASE)
        text = re.sub(r'tripo:inputs/(\d{8}-\d{6}-[A-Za-z0-9._-]+)',
                      lambda m: 'tripo:inputs/' + self.input_alias(m[1]), text)
        # Non-path source_name fields may also echo the legacy service prefix.
        text = re.sub(r'(?<=["\\])\d{8}-\d{6}-([A-Za-z0-9._-]+)(?=["\\])', r'uploaded-\1', text)
        return text

    def input_aliases(self):
        try: return json.loads((self.runtime_dir / 'input-aliases.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def resolve_input_alias(self, relative):
        return self.input_aliases().get(relative, relative)

    def input_alias(self, relative):
        with self.alias_lock:
            aliases = self.input_aliases()
            for alias, original in aliases.items():
                if original == relative: return alias
            alias = uuid.uuid4().hex + '-' + re.sub(r'^\d{8}-\d{6}-', '', relative)
            aliases[alias] = relative
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            staged = self.runtime_dir / ('input-aliases.' + uuid.uuid4().hex + '.tmp')
            staged.write_text(json.dumps(aliases), encoding='utf-8')
            staged.replace(self.runtime_dir / 'input-aliases.json')
            return alias

    def public_times(self, value):
        if isinstance(value, list): return [self.public_times(v) for v in value]
        if isinstance(value, dict):
            return {k: 'UTC' if k.lower() in ('timezone', 'time_zone', 'timezone_id') else self.public_times(v) for k, v in value.items()}
        if isinstance(value, str):
            try:
                nested = json.loads(value)
                if isinstance(nested, (dict, list)): return json.dumps(self.public_times(nested), ensure_ascii=False)
            except (ValueError, TypeError): pass
            if re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value):
                return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        return value

    def gallery_files(self):
        try:
            catalog = json.loads((self.roots['archive'] / 'catalog.json').read_text(encoding='utf-8'))
            result = {}
            for item_id, item in catalog.get('items', {}).items():
                for entry in item.get('files', []):
                    relative = entry.get('relative_path')
                    if not isinstance(relative, str) or not isinstance(entry.get('file_id'), str): continue
                    inside(self.roots['archive'], relative)
                    result['files/' + item_id + '/' + entry['file_id']] = relative
            return result
        except (OSError, ValueError, TypeError): return {}

    def tools(self):
        # The list is cached so a VPS session started during a sign-in still sees every tool.
        cache = self.runtime_dir / 'tools.json'
        try:
            self.ensure_started()
            tools = [english_tool(t) for t in self._send('tools/list').get('tools', []) if t.get('name') not in HIDDEN]
            self.runtime_dir.mkdir(parents=True, exist_ok=True); cache.write_text(json.dumps(tools), encoding='utf-8')
        except ValueError:
            try: tools = [english_tool(t) for t in json.loads(cache.read_text(encoding='utf-8')) if t.get('name') not in HIDDEN]
            except (OSError, ValueError): raise ValueError('Tripo Studio is not available on the GPU computer yet.') from None
        return {'tools': tools,
                'paths': 'Local files are tripo:inputs/<name> handles from the upload tool; results come back as tripo:archive/... or tripo:assets/... handles for the download tool.'}

    def call(self, name, arguments=None):
        if not isinstance(name, str) or not name.startswith('tripo_') or name in HIDDEN:
            raise ValueError('This Tripo tool is not exposed to the VPS.')
        arguments = arguments or {}
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 65536: raise ValueError('Tripo arguments must be an object under 64 KB.')
        result = self._call(name, arguments)
        if backend_gone(result):
            # The backend stopped under a live bootstrap (a login, an update): start a fresh one.
            # Only reads are repeated; a submission is reported so it is never sent twice.
            self.stop()
            if name.startswith(('tripo_get_', 'tripo_list_')): result = self._call(name, arguments)
        if name == 'tripo_get_workflow_capabilities': result = english_capabilities(result)
        if name == 'tripo_get_status': result = self.necessary_status(result)
        return self.public_times(json.loads(self.to_handles(json.dumps(result, ensure_ascii=False))))

    def necessary_status(self, result):
        def minimize(status):
            if not isinstance(status, dict): return status
            if 'session' not in status and 'scheduler' not in status: return status
            output = {'session': {'authenticated': bool(status.get('session', {}).get('authenticated'))}}
            if isinstance(status.get('scheduler'), dict):
                output['scheduler'] = {k: status['scheduler'][k] for k in
                    ('accepting', 'queued', 'running', 'concurrencyLimit', 'failed', 'succeeded') if k in status['scheduler']}
            if isinstance(status.get('watchdog'), dict):
                output['watchdog'] = {k: status['watchdog'][k] for k in ('state', 'running') if k in status['watchdog']}
            balance = status.get('balance', {})
            if isinstance(balance, dict):
                wallet = balance.get('summary', {}).get('wallet', {})
                output['balance'] = {'available': bool(balance.get('available')),
                    'credits': {k: wallet[k] for k in ('total_credit', 'expiring_credit') if k in wallet}}
            return output
        result = dict(result)
        if 'structuredContent' in result: result['structuredContent'] = minimize(result['structuredContent'])
        for item in result.get('content', []):
            if isinstance(item, dict) and item.get('type') == 'text':
                try: item['text'] = json.dumps(minimize(json.loads(item['text'])), ensure_ascii=False)
                except ValueError: pass
        return result

    def _call(self, name, arguments):
        self.ensure_started()
        try: return self._send('tools/call', {'name': name, 'arguments': self.to_local(arguments)}, timeout=600)
        except ValueError: raise
        except Exception:
            logging.exception('Tripo call failed')
            raise ValueError('Tripo Studio call did not complete; details stay in the local bridge log.') from None

    def upload(self, filename, content_base64):
        if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', filename) or filename.startswith('.') or pathlib.Path(filename).suffix.lower() not in UPLOAD_EXT:
            raise ValueError('Unsupported Tripo upload filename.')
        content = base64.b64decode(content_base64, validate=True)
        if len(content) > 40 * 1024**2: raise ValueError('Tripo upload exceeds 40 MB.')
        self.roots['inputs'].mkdir(parents=True, exist_ok=True)
        stamped = uuid.uuid4().hex + '-' + filename
        (self.roots['inputs'] / stamped).write_bytes(content)
        return {'path': 'tripo:inputs/' + stamped, 'bytes': len(content)}

    def file(self, handle):
        match = HANDLE.fullmatch(handle or '')
        if not match: raise ValueError('Use a tripo:inputs|assets|archive/... handle.')
        relative = (self.gallery_files().get(match[2], match[2]) if match[1] == 'archive'
                    else self.resolve_input_alias(match[2]) if match[1] == 'inputs' else match[2])
        target = inside(self.roots[match[1]], relative)
        if not target.is_file(): raise ValueError('Tripo file not found.')
        return target

    def status(self):
        try: installed = bool(self.plugin_root())
        except ValueError: installed = False
        return {'engine': 'tripo', 'region': self.region, 'installed': installed,
                'connected': self.process is not None and self.process.poll() is None}

    def login_lock(self):
        return self.runtime_dir / 'login.lock'

    def login_active(self):
        try: pid = int(self.login_lock().read_text(encoding='utf-8'))
        except (OSError, ValueError): return False
        if pid_alive(pid): return True
        self.login_lock().unlink(missing_ok=True); return False

    def start_keepalive(self):
        """Starts the plugin with the bridge and restarts it when it stops (not during a login)."""
        def loop():
            while True:
                if not self.login_active() and (self.process is None or self.process.poll() is not None):
                    try: self.ensure_started()
                    except Exception: logging.warning('Tripo Studio service is not available yet')
                time.sleep(KEEPALIVE_SECONDS)
        threading.Thread(target=loop, name='tripo-keepalive', daemon=True).start()

    def profile_dir(self):
        profile = self.data_dir / 'chrome-profile'; profile.mkdir(parents=True, exist_ok=True)
        marker = profile / MARKER
        if not marker.exists():
            if any(profile.iterdir()): raise ValueError('The Tripo profile folder is not empty and has no plugin marker.')
            token = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
            marker.write_text(json.dumps({'ownership_token': token, 'schema_version': 1}) + '\n', encoding='utf-8')
        return profile

    def open_login(self):
        """Local only: show the dedicated profile so the user signs in once by hand. The bridge's
        keep-alive waits while this process holds the login lock."""
        self.begin_login()
        self.shutdown_backend()
        browser = find_browser(self.browser)
        return subprocess.Popen([browser, '--user-data-dir=' + str(self.profile_dir()), '--no-first-run',
                                 '--no-default-browser-check', self.site['studio'] + '/workspace/generate'])

    def begin_login(self):
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self.login_active():raise ValueError('Another Tripo sign-in is already in progress.')
        try:
            with self.login_lock().open('x',encoding='utf-8') as stream:stream.write(str(os.getpid()))
        except FileExistsError:raise ValueError('Another Tripo sign-in started concurrently.') from None
        self.stop()

    def shutdown_backend(self):
        try:
            with socket.create_connection(('127.0.0.1', self.site['port']), timeout=6):pass
        except ConnectionRefusedError:return
        result=subprocess.run(['node','./mcp/server.mjs','--shutdown'],cwd=str(self.runtime_root()),
            env=self.environment(),capture_output=True,timeout=90,creationflags=NO_WINDOW)
        if result.returncode:raise ValueError('The local Tripo backend could not shut down safely.')

    def end_login(self):
        self.login_lock().unlink(missing_ok=True)
