"""Linux Git broker. The agent sees a source workspace, never this Git store.

Independent UID, Unix peer credentials, bounded fixed operations, no shell,
no external diff/hooks/filters. Provision only into a NEW test workspace first.
"""
import hashlib
import json
import os
import pathlib
import re
import socket
import stat
import struct
import subprocess
import threading
import uuid

MAX_FILE = 32 * 1024 ** 2
MAX_TOTAL = 256 * 1024 ** 2
EXCLUDED = {'.git', '.ssh', '.claude', '.codex', 'node_modules', '__pycache__', '.venv',
            '.godot', 'Library', 'Temp', 'obj', 'target'}


class BrokerError(Exception):
    pass


def filtered(text):
    text = re.sub(r'(?i)(?:https?|ssh)://[^\s<>"\x27]+|git@[^\s<>"\x27]+', '[remote]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+', '[email]', text)
    text = re.sub(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', '[address]', text)
    return text


def relative(value):
    if not isinstance(value, str) or len(value) > 1024 or '\\' in value or ':' in value or re.search(r'[\x00-\x1f\x7f]', value):
        raise BrokerError('Invalid workspace path.')
    pieces = value.split('/')
    if any(not p or p in ('.', '..') or p in EXCLUDED or p.startswith('.env') for p in pieces):
        raise BrokerError('Protected workspace path.')
    return pieces


def safe_directory(path):
    absolute = pathlib.Path(path)
    if not absolute.is_absolute():
        raise BrokerError('Absolute workspace required.')
    current = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise BrokerError('Linked workspace ancestors are not permitted.')
    return absolute


class Workspace:
    def __init__(self, path):
        self.path = safe_directory(path)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def parent(self, name, create=False):
        pieces = relative(name)
        directory = os.dup(self.fd)
        try:
            for piece in pieces[:-1]:
                if create:
                    try:
                        os.mkdir(piece, 0o770, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(piece, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                if create:
                    os.fchmod(child, 0o2770)
                os.close(directory)
                directory = child
            return directory, pieces[-1]
        except Exception:
            os.close(directory)
            raise

    def read(self, name):
        parent, leaf = self.parent(name)
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
                    raise BrokerError('Only bounded regular workspace files are accepted.')
                with os.fdopen(fd, 'rb', closefd=False) as source:
                    content = source.read(MAX_FILE + 1)
                if len(content) > MAX_FILE:
                    raise BrokerError('Workspace file exceeds limit.')
                return content, '100755' if info.st_mode & 0o111 else '100644'
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def write(self, name, content, mode):
        parent, leaf = self.parent(name, create=True)
        temporary = '.orca-' + uuid.uuid4().hex
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb', closefd=False) as out:
                    out.write(content)
                os.fchmod(fd, 0o770 if mode == '100755' else 0o660)
            finally:
                os.close(fd)
            os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    def delete(self, name):
        parent, leaf = self.parent(name)
        try:
            if not stat.S_ISREG(os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mode):
                raise BrokerError('Refusing to remove a non-regular tracked file.')
            os.unlink(leaf, dir_fd=parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent)

    def snapshot(self):
        values = {}
        total = 0
        for current, directories, files in os.walk(self.path, followlinks=False):
            directories[:] = [d for d in directories if d not in EXCLUDED and not d.startswith('.env')]
            for directory in directories:
                if pathlib.Path(current, directory).is_symlink():
                    raise BrokerError('Workspace directory links are not accepted.')
            for file in files:
                if file.startswith('.env') or file in EXCLUDED:
                    continue
                name = pathlib.Path(current, file).relative_to(self.path).as_posix()
                content, mode = self.read(name)
                total += len(content)
                if total > MAX_TOTAL or len(values) >= 10000:
                    raise BrokerError('Workspace snapshot exceeds limit; use an explicit asset strategy.')
                values[name] = (content, mode)
        return values

    def close(self):
        os.close(self.fd)


class Project:
    def __init__(self, config):
        self.config = config
        self.repo = safe_directory(config['repository'])
        self.workspace = Workspace(config['workspace'])
        self.branch = config['branch']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,127}', self.branch) or '..' in self.branch or self.branch.endswith('/'):
            raise BrokerError('Invalid configured branch.')
        self.ref = 'refs/heads/' + self.branch
        if (self.workspace.path / '.git').exists():
            raise BrokerError('Source workspace must not expose a Git repository.')
        self.git(['check-ref-format', self.ref])

    def git(self, args, data=None, check=True, index=None, network=False):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.repo.parent), 'LANG': 'C.UTF-8', 'TZ': 'UTC0',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0',
               'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', 'GIT_NO_REPLACE_OBJECTS': '1'}
        if index:
            env['GIT_INDEX_FILE'] = str(index)
        if args[0] == 'commit-tree':
            name = self.config.get('author_name', 'Developer')
            email = self.config.get('author_email', 'noreply@local.invalid')
            for key in ('AUTHOR', 'COMMITTER'):
                env['GIT_' + key + '_NAME'] = name
                env['GIT_' + key + '_EMAIL'] = email
        if network:
            key = self.config.get('key_file')
            known = self.config.get('known_hosts')
            if key:
                import shlex
                if not known:
                    raise BrokerError('Verified SSH host keys must be provisioned by the administrator.')
                env['GIT_SSH_COMMAND'] = 'ssh -oBatchMode=yes -oIdentitiesOnly=yes -oStrictHostKeyChecking=yes -i ' + shlex.quote(key) + ' -oUserKnownHostsFile=' + shlex.quote(known)
        result = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                                 '-c', 'core.attributesFile=/dev/null', '-c', 'diff.external=',
                                 '-c', 'credential.helper=', '-c', 'protocol.ext.allow=never',
                                 '--git-dir=' + str(self.repo), *args], input=data, capture_output=True,
                                timeout=300 if network else 45, env=env)
        if check and result.returncode:
            raise BrokerError('Git operation failed; the administrator can inspect the protected repository. No raw credentials or remote diagnostics are returned.')
        return result

    def head(self):
        result = self.git(['rev-parse', '--verify', self.ref], check=False)
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def tree(self, revision=None):
        revision = revision or self.head()
        if not revision:
            return {}
        entries = self.git(['ls-tree', '-rz', revision]).stdout.split(b'\0')
        values = {}
        total = 0
        for entry in entries:
            if not entry:
                continue
            meta, name = entry.split(b'\t', 1)
            mode, kind, ident = meta.decode().split()
            path = name.decode('utf-8')
            relative(path)
            if mode not in ('100644', '100755') or kind != 'blob':
                raise BrokerError('Symlinks and submodules require a separately reviewed export; not supported in this source workspace.')
            size = int(self.git(['cat-file', '-s', ident]).stdout)
            if size > MAX_FILE:
                raise BrokerError('A versioned asset exceeds the source workspace limit.')
            content = self.git(['cat-file', 'blob', ident]).stdout
            total += len(content)
            if total > MAX_TOTAL or len(values) >= 10000:
                raise BrokerError('Repository snapshot exceeds configured limits.')
            if content.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                raise BrokerError('Git LFS pointers require explicit asset provisioning; refusing to report a complete source export.')
            values[path] = (content, mode)
        return values

    def changes(self, current=None, tracked=None):
        current = self.workspace.snapshot() if current is None else current
        tracked = self.tree() if tracked is None else tracked
        return [{'path': filtered(p), 'change': 'added' if p not in tracked else 'deleted' if p not in current else 'modified'}
                for p in sorted(set(current) | set(tracked)) if current.get(p) != tracked.get(p)]

    def stage(self, snapshot, index):
        if self.head():
            self.git(['read-tree', self.ref], index=index)
        else:
            self.git(['read-tree', '--empty'], index=index)
        tracked = self.tree()
        records = []
        for name in sorted(set(tracked) - set(snapshot)):
            records.append(('0 ' + '0' * 40 + '\t' + name).encode() + b'\0')
        for name, (content, mode) in snapshot.items():
            ident = self.git(['hash-object', '-w', '--stdin'], data=content).stdout.decode().strip()
            records.append((mode + ' ' + ident + '\t' + name).encode() + b'\0')
        if records:
            self.git(['update-index', '-z', '--index-info'], data=b''.join(records), index=index)

    def call(self, operation, arguments):
        allowed = {'status': set(), 'diff': set(), 'log': {'limit'}, 'commit': {'message', 'expected_head'},
                   'fetch': set(), 'pull': {'expected_head'}, 'push': {'expected_head'}}
        if operation not in allowed or set(arguments) - allowed[operation]:
            raise BrokerError('Operation or arguments not allowed.')
        before = self.head()
        if operation == 'status':
            return {'branch': self.branch, 'head': before, 'changes': self.changes(),
                    'git_store_isolated': True, 'agent_runtime_isolation_requires_separate_verification': True}
        if operation == 'log':
            limit = arguments.get('limit', 10)
            if type(limit) is not int or not 1 <= limit <= 30:
                raise BrokerError('Log limit must be 1..30.')
            if not before:
                return {'commits': []}
            lines = self.git(['log', '-' + str(limit), '--format=%h%x00%s', self.ref]).stdout.decode(errors='replace').splitlines()
            return {'commits': [{'id': line.split('\0')[0], 'subject': filtered(line.partition('\0')[2])} for line in lines]}
        if operation in ('commit', 'pull', 'push') and arguments.get('expected_head') != before:
            raise BrokerError('Repository head changed; refresh status before writing.')
        if operation in ('commit', 'push') and not self.config.get('allow_write'):
            raise BrokerError('This project is read-only.')
        if operation in ('diff', 'commit'):
            snapshot = self.workspace.snapshot()
            index = self.repo.parent / ('index-' + uuid.uuid4().hex)
            try:
                self.stage(snapshot, index)
                if operation == 'diff':
                    patch = self.git(['diff', '--cached', '--no-ext-diff', '--no-textconv', '--no-renames',
                                      '--src-prefix=a/', '--dst-prefix=b/'], index=index).stdout
                    if len(patch) > 128 * 1024:
                        raise BrokerError('Diff too large; use status and smaller changes.')
                    return {'patch': filtered(patch.decode(errors='replace')), 'identity_fields_returned': False}
                message = arguments.get('message')
                if not isinstance(message, str) or not message.strip() or len(message) > 2000 or '\0' in message:
                    raise BrokerError('Provide a bounded commit message.')
                if not self.changes(snapshot):
                    return {'committed': False, 'head': before}
                tree = self.git(['write-tree'], index=index).stdout.decode().strip()
                args = ['commit-tree', tree] + (['-p', before] if before else [])
                ident = self.git(args, data=message.encode()).stdout.decode().strip()
                self.git(['update-ref', self.ref, ident, before or '0' * 40])
                return {'committed': True, 'head': ident}
            finally:
                index.unlink(missing_ok=True)
                index.with_name(index.name + '.lock').unlink(missing_ok=True)
        if operation in ('fetch', 'pull'):
            self.git(['fetch', '--no-tags', 'origin', '+refs/heads/' + self.branch + ':refs/remotes/origin/' + self.branch], network=True)
            target = self.git(['rev-parse', 'refs/remotes/origin/' + self.branch]).stdout.decode().strip()
            if operation == 'fetch':
                return {'fetched': True, 'head': before, 'remote_head': target}
            current = self.workspace.snapshot()
            original = self.tree()
            if self.changes(current, original):
                raise BrokerError('Workspace has changes; commit them before pulling. No implicit discard.')
            if before and self.git(['merge-base', '--is-ancestor', before, target], check=False).returncode:
                raise BrokerError('Remote update is not fast-forward. Administrator review is required; history was not rewritten.')
            wanted = self.tree(target)
            for path in sorted(set(current) - set(wanted)):
                self.workspace.delete(path)
            for path, (content, mode) in wanted.items():
                if current.get(path) != (content, mode):
                    self.workspace.write(path, content, mode)
            self.git(['update-ref', self.ref, target, before or '0' * 40])
            return {'updated': target != before, 'head': target}
        if operation == 'push':
            self.git(['push', '--porcelain', 'origin', self.ref + ':' + self.ref], network=True)
            return {'pushed': True, 'head': before}
        raise BrokerError('Unsupported operation.')


class Broker:
    def __init__(self, config, enforce_identity=True):
        self.config = config
        self.lock = threading.Lock()
        if enforce_identity:
            if os.geteuid() == 0 or any(p['agent_uid'] == os.geteuid() for p in config['projects'].values()):
                raise BrokerError('Run the broker as a dedicated non-root UID, separate from every agent.')
            root = pathlib.Path(config['store'])
            if root.stat().st_uid != os.geteuid() or stat.S_IMODE(root.stat().st_mode) != 0o700:
                raise BrokerError('Git store must be owned by the dedicated broker UID with mode 0700.')
            for project in config['projects'].values():
                repo = safe_directory(project['repository'])
                if not repo.is_relative_to(root) or repo.stat().st_uid != os.geteuid() or project['agent_uid'] == 0:
                    raise BrokerError('Every repository must stay in the protected broker store, separate from a non-root agent.')

    def handle(self, peer_uid, request):
        if not isinstance(request, dict) or set(request) - {'project_id', 'operation', 'arguments'}:
            raise BrokerError('Invalid request.')
        project_id = request.get('project_id')
        project = self.config['projects'].get(project_id)
        if not project or project['agent_uid'] != peer_uid:
            raise BrokerError('Project access denied.')
        arguments = request.get('arguments', {})
        if not isinstance(arguments, dict):
            raise BrokerError('Invalid arguments.')
        with self.lock:
            instance = Project(project)
            try:
                return instance.call(request.get('operation'), arguments)
            finally:
                instance.workspace.close()

    def serve(self):
        path = pathlib.Path(self.config['socket'])
        if path.exists():
            raise BrokerError('Socket already exists; investigate the running service before replacing it.')
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        path.chmod(0o660)
        server.listen(8)
        try:
            while True:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(15)
                    try:
                        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        data = bytearray()
                        while not data.endswith(b'\n'):
                            chunk = connection.recv(8192)
                            if not chunk:
                                raise BrokerError('Incomplete request.')
                            data.extend(chunk)
                            if len(data) > 16384:
                                raise BrokerError('Request exceeds limit.')
                        result = {'ok': True, 'result': self.handle(uid, json.loads(data))}
                    except BrokerError as error:
                        result = {'ok': False, 'error': str(error)}
                    except Exception:
                        result = {'ok': False, 'error': 'Git request did not complete; no raw diagnostics returned.'}
                    try:
                        connection.sendall(json.dumps(result).encode() + b'\n')
                    except OSError:
                        pass
        finally:
            server.close()
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=pathlib.Path)
    args = parser.parse_args()
    info = args.config.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise SystemExit('Broker config must be owned by the broker with mode 0600.')
    Broker(json.loads(args.config.read_text())).serve()
