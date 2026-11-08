"""Durable deployment state; credentials remain only in expiring connections."""
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
import zipfile
import io
from plan import validate, digest, agent_document, agent_plan
from transport import SSH, probe


def atomic_json(file, value):
    file = pathlib.Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    pending = file.with_name(file.name + '.tmp')
    with open(pending, 'w', encoding='utf-8') as out:
        if os.name != 'nt':
            os.fchmod(out.fileno(), 0o600)
        json.dump(value, out, ensure_ascii=False, indent=2)
    os.replace(pending, file)


def local_status():
    executable = shutil.which('tailscale')
    if os.name == 'nt' and not executable:
        candidate = pathlib.Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe'
        if candidate.is_file():
            executable = str(candidate)
    value = {'tailscale': {'installed': bool(executable), 'state': 'not-installed'},
             'platform': os.name, 'python_ready': True}
    if executable:
        try:
            result = subprocess.run([executable, 'status', '--json'], capture_output=True, timeout=12,
                                    creationflags=0x08000000 if os.name == 'nt' else 0)
            data = json.loads(result.stdout) if result.returncode == 0 else {}
            state = data.get('BackendState', 'backend-unavailable')
            value['tailscale'] = {'installed': True, 'state': state,
                                 'private_ips': [a for a in (data.get('Self') or {}).get('TailscaleIPs', []) if a.startswith('100.')]}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            value['tailscale'] = {'installed': True, 'state': 'backend-unavailable'}
    return value


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def resolve_orca(plan):
    """Resolve once at inspection; subsequent execution uses the saved exact asset."""
    if plan.get('orca_asset_url'):
        return plan
    tag = plan.get('orca_version')
    url = 'https://api.github.com/repos/stablyai/orca/releases/' + ('tags/' + tag if tag else 'latest')
    request = urllib.request.Request(url, headers={'User-Agent': 'Orca-Deploy/1.0', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    version = release.get('tag_name', '')
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', version):
        raise ValueError('官方 Orca 发布版本无法识别，请选择明确版本。')
    matches = [a for a in release.get('assets', []) if re.search(r'(amd64|x64).*\.deb$', a.get('name', ''), re.I)]
    if len(matches) != 1:
        raise ValueError('官方发布未找到唯一 x64 deb 包，请选择对应安装包。')
    asset = matches[0]
    result = {**plan, 'orca_version': version, 'orca_asset_url': asset['browser_download_url']}
    recorded = asset.get('digest') or ''
    if recorded.startswith('sha256:'):
        result['orca_sha256'] = recorded[7:]
    return validate(result)


def resolve_claude(plan):
    if plan.get('claude_version') != 'stable':
        return plan
    # Read, never execute, the official installer to discover its release store.
    request = urllib.request.Request('https://claude.ai/install.sh', headers={'User-Agent': 'Orca-Deploy/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        installer = response.read(256 * 1024).decode('utf-8')
    match = re.search(r'https://storage\.googleapis\.com/[A-Za-z0-9_-]+/claude-code-releases', installer)
    if not match:
        raise ValueError('无法从官方安装器锁定 Claude stable；请填写官方明确版本号后重新检查。')
    with urllib.request.urlopen(match[0] + '/stable', timeout=20) as response:
        version = response.read(100).decode().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('官方 Claude stable 版本响应无法识别；未执行安装。')
    return validate({**plan, 'claude_version': version})


class Engine:
    def __init__(self, root, transport_factory=SSH, probe_function=probe):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            self.root.chmod(0o700)
        self.transport_factory = transport_factory
        self.probe_function = probe_function
        self.connections = {}
        self.busy = set()
        self.leases = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.reaper = threading.Thread(target=self._reap, daemon=True)
        self.reaper.start()

    def _file(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('部署任务 ID 无效。')
        return self.root / (ident + '.json')

    def save(self, record):
        record['updated_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        atomic_json(self._file(record['id']), record)

    def load(self, ident):
        with self.lock:
            record = json.loads(self._file(ident).read_text(encoding='utf-8'))
            # A service restart never silently reruns an uncertain install.
            if record['status'] == 'running' and ident not in self.busy and not process_alive(record.get('worker_pid')):
                record['status'] = 'needs-inspection'
                record['message'] = '安装助手已重启；先重新检查实际状态，再继续。'
                self.save(record)
            return record

    def list(self):
        return [self.load(p.stem) for p in sorted(self.root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
                if re.fullmatch('[a-f0-9]{32}', p.stem)][:30]

    def create(self, plan):
        clean = validate(plan)
        record = {'id': uuid.uuid4().hex, 'plan': clean, 'plan_hash': digest(clean), 'status': 'draft',
                  'steps': {}, 'results': {}, 'message': '核实连接方式与 SSH 主机身份后检查。',
                  'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        with self.lock:
            self.save(record)
        return record

    def fingerprint(self, ident):
        record = self.load(ident)
        if not record['plan']['host']:
            raise ValueError('先填写 VPS 地址。')
        return self.probe_function(record['plan'])

    def connect(self, ident, identity, confirmed=False, password=None, key_file=None, key_passphrase=None):
        if confirmed is not True:
            raise ValueError('先通过可信渠道确认 SSH 主机指纹。')
        record = self.load(ident)
        if not record['plan']['host']:
            raise ValueError('先填写 VPS 地址。')
        # Never put secrets in the record, exceptions, command line or on disk.
        with self.lock:
            if ident in self.busy:
                raise ValueError('步骤正在运行，暂不更换连接。')
        transport = self.transport_factory(record['plan'], identity, password=password,
                                           key_file=key_file, key_passphrase=key_passphrase)
        with self.lock:
            old = self.connections.pop(ident, None)
            if old:
                old[0].close()
            self.connections[ident] = [transport, time.monotonic()]
            record['status'] = 'connected'
            record['host_fingerprint'] = identity
            record['message'] = '主机身份已核实，连接已建立。'
            self.save(record)
        return record

    def _transport(self, ident):
        with self.lock:
            connection = self.connections.get(ident)
            if not connection:
                raise ValueError('连接未建立或已过期；请重新认证。部署进度已保留。')
            connection[1] = time.monotonic()
            return connection[0]

    def start(self, ident, operation, approved_hash=None):
        if operation not in ('inspect', 'apply', 'service', 'verify', 'handoffs'):
            raise ValueError('不允许的部署操作。')
        with self.lock:
            record = self.load(ident)
            self._transport(ident)
            if ident in self.busy:
                raise ValueError('当前步骤尚未结束，请查询同一个任务。')
            if operation in ('apply', 'service'):
                if approved_hash != record['plan_hash'] or not record['results'].get('inspect'):
                    raise ValueError('需要先检查，并批准当前未改变的部署计划。')
                inspection = record['results']['inspect']
                if not inspection.get('supported') or not inspection.get('enough_disk') or not inspection.get('enough_memory', True):
                    raise ValueError('系统或空间检查未通过，不执行安装。')
            # Serialize the same destination even if two plans target it.
            destination = (record['plan']['host'], record['plan']['ssh_port'])
            for other in self.busy:
                active = self.load(other)['plan']
                if (active['host'], active['ssh_port']) == destination:
                    raise ValueError('同一 VPS 已有部署步骤运行，避免重复安装。')
            lock_dir = self.root / 'locks'
            lock_dir.mkdir(exist_ok=True)
            name = hashlib.sha256(repr(destination).encode()).hexdigest() + '.lock'
            lease = open(lock_dir / name, 'a+b')
            try:
                if os.name == 'nt':
                    import msvcrt
                    if lease.seek(0, 2) == 0:
                        lease.write(b'0'); lease.flush()
                    lease.seek(0)
                    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lease.close()
                raise ValueError('另一个安装助手正在处理此 VPS；先查询其任务。') from None
            self.leases[ident] = lease
            self.busy.add(ident)
            record['status'] = 'running'
            record['operation'] = operation
            record['worker_pid'] = os.getpid()
            record['message'] = '正在执行固定部署步骤。'
            self.save(record)
        threading.Thread(target=self._run, args=(ident, operation), daemon=True).start()
        return record

    def _run(self, ident, operation):
        try:
            transport = self._transport(ident)
            inspection = self.load(ident)['results'].get('inspect', {})
            if hasattr(transport, 'use_sudo'):
                transport.use_sudo = inspection.get('sudo_available', False) and not inspection.get('admin', False)
            operations = ('system', 'tailscale', 'tools') if operation == 'apply' else (operation,)
            for step in operations:
                with self.lock:
                    record = self.load(ident)
                    record['steps'][step] = 'running'
                    record['message'] = '正在执行：' + step
                    self.save(record)
                result = transport.stage(step, record['plan'])
                if step == 'inspect' and result.get('needs_orca_package'):
                    plan = resolve_orca(record['plan'])
                    record['plan'] = plan
                    record['plan_hash'] = digest(plan)
                if step == 'inspect' and result.get('components', {}).get('claude') is False:
                    plan = resolve_claude(record['plan'])
                    record['plan'] = plan
                    record['plan_hash'] = digest(plan)
                with self.lock:
                    record['results'][step] = result
                    record['steps'][step] = 'complete'
                    self.save(record)
            with self.lock:
                record['status'] = 'needs-authorization' if operation == 'apply' else 'ready'
                if operation == 'verify':
                    record['status'] = 'server-verified' if result.get('server_passed') else 'needs-attention'
                record['message'] = ('安装阶段完成。继续官方登录、首次配对和服务交接；尚未宣告部署完成。'
                                     if operation == 'apply' else '步骤完成；请查看真实结果和下一步。')
                self.save(record)
        except Exception as error:
            with self.lock:
                record = self.load(ident)
                record['status'] = 'failed'
                # All transport/stage exceptions are fixed safe messages. Unknown exceptions get no raw text.
                record['message'] = str(error)[:500] if isinstance(error, (ValueError, RuntimeError)) else '部署步骤未完成（' + type(error).__name__ + '）。'
                for step, status in record['steps'].items():
                    if status == 'running':
                        record['steps'][step] = 'failed'
                self.save(record)
        finally:
            with self.lock:
                self.busy.discard(ident)
                lease = self.leases.pop(ident, None)
                if lease:
                    lease.close()
                if ident in self.connections:
                    self.connections[ident][1] = time.monotonic()

    def export(self, ident):
        record = self.load(ident)
        stream = io.BytesIO()
        folder = pathlib.Path(__file__).parent
        stamp = time.gmtime()[:6]
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as package:
            def write(name, content):
                entry = zipfile.ZipInfo(name, date_time=stamp)
                entry.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(entry, content)
            write('DEPLOY.md', agent_document(record['plan']))
            write('deploy-plan.json', json.dumps(agent_plan(record['plan']), ensure_ascii=False, indent=2))
            write('acceptance.json', json.dumps(record['results'].get('verify', {}), ensure_ascii=False, indent=2))
            for name in ('deploy.py', 'plan.py', 'engine.py', 'transport.py', 'linux_stage.py', 'local.py', 'ui.html', 'requirements.txt', 'README.md'):
                file = folder / name
                if file.is_file():
                    write(name, file.read_bytes())
            broker = folder / 'git-broker'
            if not broker.is_dir():
                broker = folder.parent / 'git-broker'
            for name in ('broker.py', 'client.py', 'install.py', 'README.md', 'isolated-launcher.py'):
                file = broker / name
                if file.is_file():
                    write('git-broker/' + name, file.read_bytes())
            docs = folder / 'docs'
            if not docs.is_dir():
                docs = folder.parent.parent / 'docs'
            for name in ('deployment-center.md', 'claude-code-guide.md', 'vps-orca.md', 'gpu-bridge.md', 'toolkit.md', 'operations.md'):
                file = docs / name
                if file.is_file():
                    write('docs/' + name, file.read_bytes())
            for file in (docs / 'images').rglob('*'):
                if file.is_file() and not file.is_symlink() and file.suffix.lower() in ('.png', '.jpg', '.svg', '.webp'):
                    write('docs/images/' + file.relative_to(docs / 'images').as_posix(), file.read_bytes())
        return stream.getvalue()

    def _reap(self):
        while not self.stop.wait(30):
            with self.lock:
                for ident in list(self.connections):
                    connection = self.connections[ident]
                    if ident not in self.busy and time.monotonic() - connection[1] > 900:
                        connection[0].close()
                        del self.connections[ident]

    def close(self):
        self.stop.set()
        with self.lock:
            for ident, connection in list(self.connections.items()):
                if ident not in self.busy:
                    connection[0].close()
                    del self.connections[ident]
