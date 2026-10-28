"""Project-scoped adapter for the loopback-only vroid-studio-mcp editor plugin."""
import base64, json, logging, pathlib, socket, struct, threading, time, urllib.request, zlib
from native_control import inside, private_result, private_text

FIELDS = {
    'state': set(), 'status': set(), 'sections': set(),
    'create': {'gender'}, 'open': {'path'}, 'save': {'path', 'replace'},
    'export_vrm': {'path', 'format', 'title', 'author', 'replace', 'license_preset'},
    'set_vrm_license': {'path', 'replace', 'license_preset'},
    'categories': {'section'}, 'enter': {'section', 'category', 'view'},
    'presets': {'section', 'category'},
    'select_preset': {'section', 'category', 'index', 'params'},
    'set_param': {'section', 'category', 'path', 'label', 'name', 'key', 'index', 'value'},
    'camera': {'action', 'region', 'angle', 'x', 'y', 'value'},
    'screenshot': {'mode'},
    'preset_preview_list': {'section', 'category', 'indexes', 'mode'},
    'preset_preview_range': {'section', 'category', 'start', 'count', 'mode'},
    'main_menu': {'discard_changes'}, 'help': {'topic'},
}


def effective_operation(operation, arguments):
    # Old Claude sessions cache the operation enum. Keep their existing save
    # operation usable for VRM without relaxing project/path/metadata checks.
    path = arguments.get('path') if isinstance(arguments, dict) else None
    if operation == 'save' and isinstance(path, str) and path.lower().endswith('.vrm'):
        return 'export_vrm'
    return operation


def clean_png(encoded):
    """Drop PNG metadata; only model pixels and decoding chunks leave the PC."""
    data = base64.b64decode(encoded, validate=True)
    if len(data) > 8*1024**2 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid VRoid preview.')
    out = bytearray(data[:8]); pos = 8; header = False
    while pos + 12 <= len(data):
        size = struct.unpack('>I', data[pos:pos+4])[0]; end = pos+size+12
        if end > len(data): raise ValueError('Incomplete VRoid preview.')
        kind = data[pos+4:pos+8]; payload = data[pos+8:pos+8+size]
        if zlib.crc32(kind+payload) != struct.unpack('>I', data[end-4:end])[0]:
            raise ValueError('Invalid VRoid preview checksum.')
        if kind == b'IHDR':
            if size != 13: raise ValueError('Invalid VRoid preview header.')
            width, height = struct.unpack('>II', payload[:8])
            if not 1 <= width <= 8192 or not 1 <= height <= 8192: raise ValueError('VRoid preview is too large.')
            header = True
        if kind in (b'IHDR', b'PLTE', b'IDAT', b'tRNS', b'IEND'): out.extend(data[pos:end])
        pos = end
        if kind == b'IEND' and header: return base64.b64encode(out).decode()
    raise ValueError('Incomplete VRoid preview.')


class VroidControl:
    def __init__(self, native):
        self.native = native; self.process = None
        self.lock = threading.Lock(); self.start_lock = threading.Lock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def rpc(self, method, params=None, timeout=90):
        request = urllib.request.Request('http://127.0.0.1:17891/mcp/',
            json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).encode(),
            {'Content-Type': 'application/json', 'Accept': 'application/json'})
        with self.opener.open(request, timeout=timeout) as response:
            data = response.read(12*1024**2+1)
        if len(data) > 12*1024**2: raise ValueError('VRoid response exceeds the transfer limit.')
        value = json.loads(data)
        if 'error' in value: raise ValueError('VRoid rejected the operation. Check editor state and arguments.')
        return value['result']

    def settings_ready(self):
        exe = pathlib.Path(self.native.config.get('native', {}).get('vroid_executable', ''))
        try:
            value = json.loads((exe.parent/'BepInEx/config/com.kokokoshka.vroidstudiomcp.servers.json').read_text())
            return value.get('enabled') is True and value.get('tcp') == '127.0.0.1:17890' and value.get('mcp') == '127.0.0.1:17891' and value.get('dev_tools') is False and value.get('debug_artifacts') is False
        except (OSError, ValueError): return False

    def status(self):
        installed = pathlib.Path(self.native.config.get('native', {}).get('vroid_executable', '')).is_file()
        return {'engine': 'vroid', 'installed': installed,
                'network_isolated': installed and self.native.guard.ready('vroid'),
                'connected': self.process is not None and self.process.poll() is None,
                'adapter_ready': self.settings_ready()}

    def ensure_started(self):
        self.native.guard.require('vroid')
        if not self.settings_ready(): raise ValueError('VRoid MCP loopback configuration is not ready. Run the local VRoid installer.')
        with self.start_lock:
            if self.process is not None and self.process.poll() is None: return
            # Never attach to an unrelated local editor listening on the same port.
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(('127.0.0.1', 17891)) == 0:
                    raise ValueError('The VRoid MCP port is already occupied by another editor. Close that editor first.')
            if self.process is not None: self.process.close()
            exe = pathlib.Path(self.native.config['native']['vroid_executable'])
            # Unity can keep its API queue alive with SW_HIDE while rendering only
            # black pixels. Show the editor without taking keyboard focus.
            self.process = self.native.process_factory([str(exe), '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720', '-logFile', str(self.native.root/'vroid-unity.log')], exe.parent, self.native.root/'vroid.log', show_window=True)
            deadline = time.monotonic()+180
            while time.monotonic() < deadline:
                if self.process.poll() is not None: raise ValueError('Managed VRoid stopped. Check the local VRoid log.')
                try: self.rpc('ping', timeout=2); return
                except Exception: time.sleep(0.5)
            raise ValueError('VRoid is still starting. Check the local editor before retrying an edit.')

    def validate(self, root, operation, arguments):
        operation = effective_operation(operation, arguments)
        if operation not in FIELDS or not isinstance(arguments, dict) or set(arguments)-FIELDS[operation]:
            raise ValueError('VRoid operation or argument is not exposed.')
        if len(json.dumps(arguments, allow_nan=False)) > 32768: raise ValueError('VRoid arguments exceed 32 KB.')
        args = dict(arguments)
        if operation == 'set_param':
            selectors = [key for key in ('path','label','name','key','index') if key in args]
            if len(selectors) != 1 or not {'section','category','value'}.issubset(args):
                raise ValueError('set_param requires section, category, value and exactly one parameter selector.')
            selector = args.pop(selectors[0])
            if type(selector) not in (str,int) or not str(selector) or len(str(selector)) > 2048:
                raise ValueError('Invalid VRoid parameter selector.')
            # Upstream calls the selector "index", even when it is a stable path.
            args['index'] = str(selector)
        if operation in ('open', 'save', 'export_vrm', 'set_vrm_license'):
            file = inside(root, args.get('path'))
            suffix = '.vrm' if operation in ('export_vrm', 'set_vrm_license') else '.vroid'
            if file.suffix.lower() != suffix: raise ValueError('Use a project-relative '+suffix+' file.')
            if operation == 'open' and not file.is_file(): raise ValueError('VRoid project file is unavailable.')
            if operation in ('save', 'export_vrm', 'set_vrm_license'):
                if 'replace' in args and type(args['replace']) is not bool: raise ValueError('replace must be boolean.')
                if file.exists() and args.get('replace') is not True: raise ValueError('File exists; replace=true is required.')
                if not file.parent.is_dir(): raise ValueError('Create the destination folder through the project first.')
            if operation == 'set_vrm_license' and (not file.is_file() or args.get('replace') is not True):
                raise ValueError('Select an existing .vrm and explicitly set replace=true to update its license.')
            if operation not in ('export_vrm', 'set_vrm_license'): args.pop('replace', None)
            args['path'] = str(file)
        if operation in ('export_vrm', 'set_vrm_license'):
            from native_vrm import PRESETS
            if args.get('license_preset', 'commercial_modifiable') not in PRESETS:
                raise ValueError('license_preset must be commercial_modifiable or restrictive.')
        if operation == 'export_vrm':
            if args.get('format', '1.0') not in ('1.0', '0.0'): raise ValueError('VRM format must be 1.0 or 0.0.')
            args['format'] = args.get('format', '1.0')
            for field in ('title', 'author'):
                value = args.get(field)
                if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
                    raise ValueError('VRM '+field+' must be 1 to 200 printable characters.')
        if operation == 'main_menu':
            if args.get('discard_changes') is not True: raise ValueError('Save first, then explicitly set discard_changes=true to leave the model.')
            args = {}
        if operation in ('screenshot', 'preset_preview_list', 'preset_preview_range'):
            if args.get('mode', 'inline') != 'inline': raise ValueError('Only model previews in inline mode are exposed.')
            args['mode'] = 'inline'
        if operation == 'camera' and args.get('action') not in ('reset', 'frame', 'angles', 'zoom', 'pan', 'rotate', 'projection', 'view'):
            raise ValueError('Camera action is not exposed.')
        if operation == 'preset_preview_list' and (not isinstance(args.get('indexes'), list) or not 1 <= len(args['indexes']) <= 12):
            raise ValueError('Request 1 to 12 preset previews.')
        if operation == 'preset_preview_range' and (type(args.get('count', 1)) is not int or not 1 <= args.get('count', 1) <= 12):
            raise ValueError('Request 1 to 12 preset previews.')
        return args

    def tools(self):
        return {'operations': sorted(FIELDS), 'paths': 'open reads .vroid; save writes .vroid source or .vrm through the compatible export route; export_vrm writes .vrm. All paths are project-relative. Writes require an explicit path and replace=true for existing files.',
                'arguments': {key: sorted(value | FIELDS['export_vrm'] if key == 'save' else value) for key, value in FIELDS.items()},
                'workflow': 'state; create(gender=female|male) or open(path); categories(section); presets/enter(section,category); select_preset(index)/set_param(value); camera; screenshot; save(path); export_vrm(path,format=1.0|0.0,title,author). Export returns to editing. Download the .vrm with download_project_file or import it with Blender import_asset. Sections and categories are case-sensitive. Use help for editor semantics.',
                'compatibility': 'If an existing Claude session rejects operation=export_vrm as Invalid option for operation, call operation=save with the same .vrm path, title, author, format and replace arguments. This invokes the identical native exporter and needs no session restart. Saving .vroid still saves editable source.',
                'license_defaults': 'commercial_modifiable: commercial use (including corporations), modification and redistribution allowed; attribution required. VRM 1.0 permission fields or VRM 0.x CC_BY metadata are written atomically. Set license_preset=restrictive to opt out. Update existing files with set_vrm_license(path,replace=true,license_preset?).',
                'limitations': ['export_vrm requires the Toolkit Studio export extension, installed with scripts/install-vroid-export.py. Title/author are explicit; saved local contact details are not copied.', 'No shell, batch/raw protocol, full-window screenshots or diagnostic tools.']}

    def call(self, project_id, operation, arguments=None):
        _, root = self.native.project(project_id)
        operation = effective_operation(operation, arguments or {})
        args = self.validate(root, operation, arguments or {})
        export_receipt = None
        try:
            if operation == 'set_vrm_license':
                from native_vrm import set_license
                if not self.lock.acquire(blocking=False): raise ValueError('VRoid is busy. Query status before changing its files.')
                try: receipt = set_license(args['path'], args.get('license_preset', 'commercial_modifiable'))
                finally: self.lock.release()
                return {'content': [{'type': 'text', 'text': json.dumps({'saved': True, 'path': arguments['path'], **receipt})}], 'isError': False}
            self.ensure_started()
            if operation in ('camera','screenshot','preset_preview_list','preset_preview_range') and self.process is not None:
                self.process.show_without_focus()
            # status bypasses a long editor edit; never retry a timed-out mutation.
            if operation == 'status': result = self.rpc('tools/call', {'name': operation, 'arguments': args}, timeout=10)
            else:
                if not self.lock.acquire(blocking=False): raise ValueError('VRoid is busy. Query status before submitting another edit.')
                try:
                    if operation == 'export_vrm':
                        result = self.rpc('tools/call', {'name': operation, 'arguments': {k:v for k,v in args.items() if k != 'license_preset'}}, timeout=285)
                        if not result.get('isError'):
                            from native_vrm import set_license
                            file = inside(root, arguments['path'])
                            if not file.is_file(): raise ValueError('VRM export did not produce a project file.')
                            export_receipt = set_license(file, args.get('license_preset', 'commercial_modifiable'))
                    else: result = self.rpc('tools/call', {'name': operation, 'arguments': args})
                finally: self.lock.release()
            filtered = self.filtered(result)
            if operation == 'export_vrm' and not filtered['isError']:
                # Return a usable relative path, never the Windows absolute path.
                filtered['content'] = [{'type': 'text', 'text': json.dumps({'saved': True,
                    'path': arguments['path'], **export_receipt})}]
            return filtered
        except ValueError: raise
        except Exception:
            logging.exception('VRoid operation failed')
            raise ValueError('VRoid operation did not complete. Query status before repeating an edit; details stay in the local log.') from None

    def filtered(self, result):
        content = []; total = 0
        for item in result.get('content', [])[:24]:
            if item.get('type') == 'text':
                text = item.get('text', '')
                try: text = json.dumps(private_result(json.loads(text)), ensure_ascii=False)
                except ValueError: text = private_text(text)[:16000]
                content.append({'type': 'text', 'text': text})
            elif item.get('type') == 'image' and item.get('mimeType') == 'image/png':
                image = clean_png(item['data']); total += len(image)
                if total > 11*1024**2: raise ValueError('VRoid preview batch is too large.')
                content.append({'type': 'image', 'mimeType': 'image/png', 'data': image})
        return {'content': content, 'isError': bool(result.get('isError'))}
