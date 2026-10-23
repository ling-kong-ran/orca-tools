#!/usr/bin/env python3
"""Loopback-only account panel for the VPS's existing Orca runtime."""
import argparse
import importlib.util
import json
import pathlib
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
PORT = 18766
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()


class PanelError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AccountBackend:
    def __init__(self, helper_path):
        spec = importlib.util.spec_from_file_location('claude_account_helper', helper_path)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)

    def state(self):
        result = self.helper.rpc('accounts.list', {'refreshUsage': False})
        state = dict(result['claude'])
        state['_limits'] = result.get('rateLimits', {})
        return state

    def refresh_usage(self):
        self.helper.rpc('accounts.list', {'refreshUsage': True})

    def select(self, account_id):
        self.helper.rpc('accounts.selectClaude', {'accountId': account_id})


def masked_email(email):
    local, separator, domain = (email or '').partition('@')
    if not separator or not local or not domain:
        return '***'
    return local[0] + '***@' + domain


def account_usage(state, account_id):
    limits = state.get('_limits', {})
    usage = None
    if account_id == state.get('activeAccountId'):
        candidate = limits.get('claude', {})
        if candidate.get('usageMetadata', {}).get('authProvenance') in ('managed:' + account_id, 'profile:' + account_id):
            usage = candidate
    else:
        usage = next((a.get('rateLimits') for a in limits.get('inactiveClaudeAccounts', [])
                      if a.get('accountId') == account_id), None)
    if not usage:
        return None
    result = {'updatedAt': usage.get('updatedAt'), 'status': usage.get('status')}
    for key in ('session', 'weekly'):
        window = usage.get(key)
        result[key] = {k: window.get(k) for k in ('usedPercent', 'resetsAt')} if window else None
    return result


def public_state(backend):
    state = backend.state()
    return {
        'host': 'remote',
        'serverName': 'Claude Accounts',
        'activeAccountId': state.get('activeAccountId'),
        'accounts': [{'id': a['id'], 'email': masked_email(a.get('email', '')),
                      'current': a['id'] == state.get('activeAccountId'),
                      'usage': account_usage(state, a['id']),
                      'needsSignIn': a.get('needsSignIn', False)}
                     for a in state.get('accounts', [])],
    }


def select_account(backend, request):
    account_id = request.get('accountId')
    state = backend.state()
    if account_id not in [a['id'] for a in state.get('accounts', [])]:
        raise PanelError('Account not found. Refresh to try again.', 400)
    account = next(a for a in state['accounts'] if a['id'] == account_id)
    if account.get('needsSignIn'):
        raise PanelError('Sign in again to use this account.', 409)
    current = state.get('activeAccountId')
    if current == account_id:
        return public_state(backend)
    if request.get('expectedActiveAccountId') != current:
        raise PanelError('The active account has changed. Refresh before switching.', 409)
    backend.select(account_id)
    result = public_state(backend)
    if result['activeAccountId'] != account_id:
        raise PanelError('Switch not confirmed. Refresh to check the active account.', 502)
    return result


def make_handler(backend, port):
    expected_host = f'127.0.0.1:{port}'
    expected_origin = f'http://{expected_host}'

    class Handler(BaseHTTPRequestHandler):
        server_version = 'VPSAccountPanel/1.0'

        def log_message(self, *_args):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; connect-src 'self'; img-src data:; "
                             "style-src 'unsafe-inline'; script-src 'nonce-" + TOKEN +
                             "'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, api=False, write=False):
            if self.headers.get('Host') != expected_host:
                raise PanelError('Invalid host.', 403)
            if api and not secrets.compare_digest(self.headers.get('X-Panel-Token', ''), TOKEN):
                raise PanelError('Session expired. Refresh the page.', 403)
            if write and self.headers.get('Origin') != expected_origin:
                raise PanelError('Invalid request origin.', 403)

        def guarded(self, action):
            try:
                action()
            except PanelError as exc:
                self.send(exc.status, {'error': str(exc)})
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                # No metadata, credentials, request tokens, or stack traces reach the page.
                print('Panel request failed:', type(exc).__name__, flush=True)
                self.send(502, {'error': 'Unable to connect to Orca. Check the connection and refresh.'})

        def do_GET(self):
            def action():
                self.authorized(api=self.path.startswith('/api/'))
                if self.path == '/':
                    html = (ROOT / 'index.html').read_text(encoding='utf-8').replace('__PANEL_TOKEN__', TOKEN)
                    self.send(200, html.encode(), 'text/html; charset=utf-8')
                elif self.path in ('/api/accounts', '/api/accounts?refresh=1'):
                    if self.path.endswith('?refresh=1'):
                        backend.refresh_usage()
                    self.send(200, public_state(backend))
                elif self.path == '/favicon.ico':
                    self.send(204, b'', 'image/x-icon')
                else:
                    self.send(404, {'error': 'Page not found.'})
            self.guarded(action)

        def do_POST(self):
            def action():
                self.authorized(api=True, write=True)
                if self.path != '/api/select':
                    raise PanelError('Endpoint not found.', 404)
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    raise PanelError('Invalid request format.', 415)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise PanelError('Invalid request size.', 400)
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or set(request) != {'accountId', 'expectedActiveAccountId'}:
                    raise PanelError('Invalid selection.', 400)
                if not LOCK.acquire(blocking=False):
                    raise PanelError('A switch is in progress. Please wait.', 409)
                try:
                    self.send(200, select_account(backend, request))
                finally:
                    LOCK.release()
            self.guarded(action)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--helper', type=pathlib.Path, default=ROOT.parent / 'claude-account.py')
    args = parser.parse_args()
    backend = AccountBackend(args.helper)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(backend, args.port))
    print(f'Account panel: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
