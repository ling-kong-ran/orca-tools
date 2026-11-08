"""Local-only installer API and independent agent CLI. Python 3.10+, no Codex."""
import argparse
import base64
import getpass
import hashlib
import hmac
import http.server
import json
import os
import pathlib
import secrets
import sys
import threading
import time
import webbrowser

# Import caches must not mutate reviewed plugin files or portable package trees.
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).parent))
# Packaged SSH wheels live here, not in a system Python installation.
dependencies = pathlib.Path(__file__).parent / 'dependencies'
if dependencies.is_dir():
    sys.path.insert(0, str(dependencies))
from engine import Engine, local_status
from local import LocalActions


def data_dir():
    if os.name == 'nt':
        return pathlib.Path(os.environ.get('LOCALAPPDATA', pathlib.Path.home() / 'AppData/Local')) / 'OrcaTools/deploy'
    return pathlib.Path.home() / '.local/state/orca-deploy'


def serve(engine, port=0, parent_stdio=False, open_browser=False):
    token = secrets.token_hex(32)
    local_actions = LocalActions(engine.root)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            content = value if isinstance(value, bytes) else (value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode())
            self.send_response(status)
            for name, item in {'Content-Type': content_type, 'Content-Length': str(len(content)),
                               'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                               'Referrer-Policy': 'no-referrer',
                               'Content-Security-Policy': "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-" + token + "'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}.items():
                self.send_header(name, item)
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            origin = 'http://127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != origin[7:]:
                return self.send(403, {'error': 'Invalid Host.'})
            if self.command == 'GET' and self.path == '/':
                source = pathlib.Path(__file__).with_name('ui.html').read_text(encoding='utf-8')
                html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Orca 部署中心</title><body>' + source.replace('__TOKEN__', token) + '</body></html>'
                return self.send(200, html, 'text/html; charset=utf-8')
            supplied = self.headers.get('X-Toolkit-Token', '')
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return self.send(403, {'error': 'Session changed. Reload this page.'})
            try:
                if self.command == 'GET' and self.path == '/api/deploy/state':
                    local_tasks = []
                    for file in sorted(engine.root.glob('local-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                        try:
                            local_tasks.append(json.loads(file.read_text(encoding='utf-8-sig')))
                        except (OSError, ValueError):
                            pass
                    return self.send(200, {'plans': engine.list(), 'local': local_status(), 'local_tasks': local_tasks})
                if self.command != 'POST' or not self.path.startswith(('/api/deploy/', '/api/deploy-local/')):
                    return self.send(404, {'error': 'Not found.'})
                # The parent adapter authenticates over its own protected local channel.
                if self.headers.get('Origin') != origin:
                    return self.send(403, {'error': 'Invalid Origin.'})
                if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send(415, {'error': 'Expected bounded JSON.'})
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    return self.send(413, {'error': 'Request too large.'})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('需要 JSON 对象。')
                if self.path.startswith('/api/deploy-local/'):
                    return self.send(200, local_actions.call(self.path.removeprefix('/api/deploy-local/'), body))
                action = self.path.removeprefix('/api/deploy/')
                allowed = {'create': {'plan'}, 'probe': {'id'},
                           'connect': {'id', 'fingerprint', 'confirmed', 'password', 'key_file', 'key_passphrase'},
                           'run': {'id', 'operation', 'approved_hash'}, 'get': {'id'}, 'export': {'id'}}
                if action not in allowed or set(body) - allowed[action]:
                    raise ValueError('不允许的部署接口或字段。')
                if action == 'create':
                    return self.send(201, engine.create(body['plan']))
                if action == 'probe':
                    return self.send(200, engine.fingerprint(body['id']))
                if action == 'connect':
                    for field in ('password', 'key_file', 'key_passphrase'):
                        if body.get(field) is not None and (not isinstance(body[field], str) or len(body[field]) > 4096 or '\0' in body[field]):
                            raise ValueError('认证输入无效。')
                    return self.send(200, engine.connect(body['id'], body['fingerprint'], body.get('confirmed'),
                                                        body.get('password'), body.get('key_file'), body.get('key_passphrase')))
                if action == 'run':
                    return self.send(202, engine.start(body['id'], body['operation'], body.get('approved_hash')))
                if action == 'get':
                    return self.send(200, engine.load(body['id']))
                if action == 'export':
                    return self.send(200, {'filename': 'orca-agent-deploy.zip',
                                           'content_base64': base64.b64encode(engine.export(body['id'])).decode()})
            except (KeyError, ValueError, RuntimeError) as error:
                self.send(400, {'error': str(error)[:600]})
            except Exception:
                self.send(500, {'error': '安装助手请求未完成；不会返回原始凭据或日志。'})

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = os.name != 'nt'

        def handle_error(self, *args):
            pass

    server = Server(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:' + str(server.server_port) + '/'
    if parent_stdio:
        # This line belongs only to the private parent process pipe, never a log.
        print(json.dumps({'url': url, 'token': token}), flush=True)
        def parent_watch():
            sys.stdin.buffer.read()
            server.shutdown()
        threading.Thread(target=parent_watch, daemon=True).start()
    else:
        print('Orca 部署中心：' + url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        engine.close()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=pathlib.Path, default=data_dir())
    sub = parser.add_subparsers(dest='operation', required=True)
    server = sub.add_parser('serve')
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--parent-stdio', action='store_true')
    server.add_argument('--open', action='store_true')
    create = sub.add_parser('create')
    create.add_argument('--plan', type=pathlib.Path, required=True)
    sub.add_parser('list')
    for operation in ('probe', 'inspect', 'apply', 'service', 'verify', 'handoffs', 'export'):
        command = sub.add_parser(operation)
        command.add_argument('--id', required=True)
        if operation not in ('probe', 'export'):
            command.add_argument('--fingerprint', required=True)
            command.add_argument('--password-prompt', action='store_true')
            command.add_argument('--key-file')
            command.add_argument('--approved-hash')
        if operation == 'export':
            command.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    engine = Engine(args.data_dir)
    try:
        if args.operation == 'serve':
            serve(engine, args.port, args.parent_stdio, args.open)
            return
        if args.operation == 'create':
            result = engine.create(json.loads(args.plan.read_text(encoding='utf-8-sig')))
        elif args.operation == 'list':
            result = engine.list()
        elif args.operation == 'probe':
            result = engine.fingerprint(args.id)
        elif args.operation == 'export':
            args.output.write_bytes(engine.export(args.id))
            result = {'saved': str(args.output)}
        else:
            password = getpass.getpass('SSH password (not saved): ') if args.password_prompt else None
            engine.connect(args.id, args.fingerprint, True, password=password, key_file=args.key_file)
            engine.start(args.id, args.operation, args.approved_hash)
            while args.id in engine.busy:
                time.sleep(.2)
            result = engine.load(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if args.operation != 'serve':
            engine.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)
