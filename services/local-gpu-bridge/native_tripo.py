"""Tripo Studio through the user's own Studio account (Ador-able/tripo-studio-mcp).

The account, its dedicated browser profile and any saved credential stay on this computer; the VPS
sees only the plugin's workflow tools. Local files cross the bridge as tripo:<root>/<relative>
handles, never as Windows paths. The China site (studio.tripo3d.com) serves the same Studio API on
other hosts, so region "cn" runs a copy of the plugin with its site addresses and loopback port
changed, with its own data directory, browser profile and debug port.
"""
import base64, hashlib, json, logging, os, pathlib, re, shutil, subprocess, threading, time

HOME = pathlib.Path(os.environ.get('USERPROFILE') or pathlib.Path.home())
LOCAL = pathlib.Path(os.environ.get('LOCALAPPDATA') or HOME / 'AppData/Local')
PLUGIN_CACHE = HOME / '.codex/plugins/cache/tripo-studio/tripo-studio-mcp'
REGIONS = {
    'global': {'studio': 'https://studio.tripo3d.ai', 'api': 'https://api.tripo3d.ai', 'account': 'https://www.tripo3d.ai',
               'port': 32175, 'cdp': 9222, 'data': 'TripoStudioMCP'},
    'cn': {'studio': 'https://studio.tripo3d.com', 'api': 'https://api-cn.tripo3d.com', 'account': 'https://www.tripo3d.com',
           'port': 32176, 'cdp': 9223, 'data': 'TripoStudioMCP-cn'},
}
PATCH_VERSION = 1
# Credentials, account switching and the local gallery never cross the bridge.
HIDDEN = {'tripo_set_account', 'tripo_clear_account', 'tripo_open_gallery'}
HANDLE = re.compile(r'tripo:(inputs|assets|archive)/([^\x00-\x1f"<>|?*]{1,512})')
UPLOAD_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.glb', '.gltf', '.obj', '.fbx', '.stl'}
MARKER = '.tripo-studio-mcp-profile'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


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
        'mcp/server.mjs': [(f'var STUDIO_ORIGIN = "{base["studio"]}";', f'var STUDIO_ORIGIN = "{site["studio"]}";'),
                           (f'var STUDIO_API_BASE_URL = "{base["api"]}";', f'var STUDIO_API_BASE_URL = "{site["api"]}";'),
                           (f'var TRIPO_ACCOUNT_ORIGIN = "{base["account"]}";', f'var TRIPO_ACCOUNT_ORIGIN = "{site["account"]}";'),
                           (f':{host(base["studio"])}`', f':{host(site["studio"])}`'), port],
        'mcp/bootstrap.mjs': [port],
    }


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
        self.pending = {}; self.next_id = 1

    def plugin_root(self):
        versions = sorted(p for p in self.cache.glob('*') if (p / 'mcp/bootstrap.mjs').is_file())
        if not versions: raise ValueError('Tripo Studio plugin is not installed on the GPU computer.')
        return versions[-1]

    def runtime_root(self):
        source = self.plugin_root(); edits = patches(self.region)
        if not edits: return source
        digest = hashlib.sha256(b''.join((source / name).read_bytes() for name in sorted(edits))).hexdigest()
        target = self.runtime_dir / source.name; stamp = target / '.bridge-patch.json'
        try:
            if json.loads(stamp.read_text(encoding='utf-8')) == {'source': digest, 'patch': PATCH_VERSION, 'region': self.region}: return target
        except (OSError, ValueError): pass
        staging = target.with_name(target.name + '.staging')
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
        shutil.rmtree(target, ignore_errors=True); staging.rename(target)
        return target

    def environment(self):
        env = dict(os.environ, NODE_USE_ENV_PROXY='1', TRIPO_DATA_DIR=str(self.data_dir),
                   TRIPO_CHROME_CDP_URL=f'http://127.0.0.1:{self.site["cdp"]}')
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
            return str(inside(self.roots[match[1]], match[2])) if match else value
        if isinstance(value, list): return [self.to_local(v) for v in value]
        if isinstance(value, dict): return {k: self.to_local(v) for k, v in value.items()}
        return value

    def to_handles(self, text):
        # Results nest JSON in JSON, so a separator may be any run of backslashes; a segment
        # never contains one, which keeps an escaped closing quote (\") out of the path.
        sep = r'(?:\\+|/)'
        for name in ('inputs', 'archive', 'assets'):
            parts = [p for p in re.split(r'[\\/]+', str(self.roots[name].resolve())) if p]
            pattern = sep.join(re.escape(p) for p in parts) + r'(?=[\\/"\s]|$)((?:' + sep + r'[^"\\/\n\r]+)*)'
            text = re.sub(pattern, lambda m: 'tripo:' + name + '/' + '/'.join(p for p in re.split(r'[\\/]+', m[1]) if p),
                          text, flags=re.IGNORECASE)
        return text

    def tools(self):
        self.ensure_started()
        tools = [t for t in self._send('tools/list').get('tools', []) if t.get('name') not in HIDDEN]
        return {'region': self.region, 'tools': tools,
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
        return json.loads(self.to_handles(json.dumps(result, ensure_ascii=False)))

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
        stamped = time.strftime('%Y%m%d-%H%M%S-') + filename
        (self.roots['inputs'] / stamped).write_bytes(content)
        return {'path': 'tripo:inputs/' + stamped, 'bytes': len(content)}

    def file(self, handle):
        match = HANDLE.fullmatch(handle or '')
        if not match: raise ValueError('Use a tripo:inputs|assets|archive/... handle.')
        target = inside(self.roots[match[1]], match[2])
        if not target.is_file(): raise ValueError('Tripo file not found.')
        return target

    def status(self):
        try: installed = bool(self.plugin_root())
        except ValueError: installed = False
        return {'engine': 'tripo', 'region': self.region, 'installed': installed,
                'connected': self.process is not None and self.process.poll() is None}

    def profile_dir(self):
        profile = self.data_dir / 'chrome-profile'; profile.mkdir(parents=True, exist_ok=True)
        marker = profile / MARKER
        if not marker.exists():
            if any(profile.iterdir()): raise ValueError('The Tripo profile folder is not empty and has no plugin marker.')
            token = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
            marker.write_text(json.dumps({'ownership_token': token, 'schema_version': 1}) + '\n', encoding='utf-8')
        return profile

    def open_login(self):
        """Local only: show the dedicated profile so the user signs in once by hand."""
        self.stop()
        root = self.runtime_root()
        subprocess.run(['node', './mcp/server.mjs', '--shutdown'], cwd=str(root), env=self.environment(),
                       capture_output=True, timeout=60, creationflags=NO_WINDOW)
        browser = find_browser(self.browser)
        return subprocess.Popen([browser, '--user-data-dir=' + str(self.profile_dir()), '--no-first-run',
                                 '--no-default-browser-check', self.site['studio'] + '/workspace/generate'])
