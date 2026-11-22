"""Dedicated host-only VM gateway. Never exposes the upstream Bridge credential."""
import argparse
import hmac
import http.server
import ipaddress
import json
from pathlib import Path
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

PRIVATE_NETWORKS = tuple(map(ipaddress.ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
MAX_BODY = 64 * 1024**2


def private_ip(value):
    address = ipaddress.ip_address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError('A dedicated RFC1918 address is required.')
    return str(address)


def validate(config):
    private_ip(config['listen']); private_ip(config['peer'])
    if config['listen'] == config['peer']:
        raise ValueError('Host and VM addresses must differ.')
    if type(config['port']) is not int or not 1024 <= config['port'] <= 65535:
        raise ValueError('Invalid relay port.')
    if not isinstance(config['token'], str) or len(config['token']) < 32:
        raise ValueError('Invalid VM credential.')
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def handler(config):
    validate(config)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    slots = threading.BoundedSemaphore(16)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_response(self, code, message=None):
            # Do not expose the interpreter version or unnecessary host metadata.
            self.send_response_only(code, message)

        def send_error(self, code, message=None, explain=None):
            self.error(code, 'Unsupported or malformed GPU request.')

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def error(self, status, message):
            data = json.dumps({'error': message}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self):
            if (self.client_address[0] != config['peer'] or self.headers.get('Origin') is not None or
                    len(self.headers.get_all('Authorization', [])) != 1 or
                    not hmac.compare_digest(self.headers.get('Authorization', '').encode(),
                                            ('Bearer ' + config['token']).encode())):
                return self.error(403, 'VM access denied.')
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/v1/') or '\\' in self.path:
                return self.error(404, 'Only GPU API routes are exposed.')
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
                return self.error(400, 'Unsupported request framing.')
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= MAX_BODY or (self.command == 'GET' and size):
                    raise ValueError()
            except ValueError:
                return self.error(413, 'Invalid request size.')
            if not slots.acquire(blocking=False):
                return self.error(503, 'GPU gateway busy; retry the same request later.')
            started = False
            try:
                body = self.rfile.read(size) if self.command == 'POST' else None
                if body is not None and len(body) != size:
                    return self.error(400, 'Incomplete request.')
                # Reload only this private local file; no upstream address comes from the VM.
                upstream = json.loads(Path(config['bridge_config']).read_text(encoding='utf-8'))
                address = ipaddress.ip_address(upstream['listen'])
                if address not in ipaddress.ip_network('100.64.0.0/10') and not address.is_loopback:
                    raise ValueError('Invalid upstream.')
                url = 'http://' + str(address) + ':' + str(int(upstream['port'])) + self.path
                request = urllib.request.Request(url, data=body, method=self.command, headers={
                    'Authorization': 'Bearer ' + upstream['token'], 'Content-Type': 'application/json'})
                try:
                    response = opener.open(request, timeout=650)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    if 300 <= response.status < 400:
                        return self.error(502, 'GPU redirects are not allowed.')
                    self.send_response(response.status)
                    for name in ('Content-Type', 'Content-Length', 'Content-Disposition'):
                        if value := response.headers.get(name):
                            self.send_header(name, value)
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers(); started = True
                    while chunk := response.read(1024 * 1024):
                        self.wfile.write(chunk)
            except (OSError, ValueError, KeyError, urllib.error.URLError):
                if not started:
                    self.error(502, 'GPU Bridge unavailable. Inspect the host service; do not resubmit edits blindly.')
            finally:
                slots.release()

        do_GET = do_POST = handle_request

    return Handler


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        pass  # Never dump credentials, request payloads or local paths.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = validate(json.loads(Path(args.config).read_text(encoding='utf-8')))
    with Server((config['listen'], config['port']), handler(config)) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
