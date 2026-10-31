"""Loopback-only workflow approval UI. This interface is never exposed to the VPS."""
import argparse, hmac, http.server, json, pathlib, secrets, threading,subprocess
from bridge import atomic_json, validate_workflow

def start_admin(bridge, port=18773):
    token=secrets.token_hex(32)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,code,data,kind='application/json; charset=utf-8'):
            value=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(value)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',f"default-src 'none'; script-src 'nonce-{token}'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(value)
        def handle_request(self):
            expected=f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host')!=expected:return self.send(403,{'error':'Invalid host'})
            if self.command=='GET' and self.path=='/':
                html=(pathlib.Path(__file__).parent/'admin.html').read_text(encoding='utf-8').replace('__TOKEN__',token)
                return self.send(200,html.encode(),'text/html; charset=utf-8')
            if not hmac.compare_digest(self.headers.get('X-Admin-Token','').encode(),token.encode()):return self.send(403,{'error':'Reload this page.'})
            try:
                if self.command=='GET' and self.path=='/api/workflows':return self.send(200,{'workflows':bridge.catalog()})
                if self.command=='GET' and self.path=='/api/native':
                    return self.send(200,{**bridge.native.status(local=True),'plans':[bridge.native.public_plan(p) for p in sorted(bridge.native.plans.values(),key=lambda p:p['created_at'],reverse=True)[:20]],'jobs':[bridge.native.public_job(j) for j in sorted(bridge.native.jobs.values(),key=lambda j:j['created_at'],reverse=True)[:30]]})
                if self.command=='POST' and self.path in ('/api/native/project','/api/native/stop-blender','/api/native/setup','/api/native/git','/api/native/unity-start','/api/native/unity-stop','/api/native/blender-cancel'):
                    if self.headers.get('Origin')!='http://'+expected:return self.send(403,{'error':'Invalid origin'})
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536:raise ValueError('Invalid request size.')
                    body=json.loads(self.rfile.read(size))
                    if self.path=='/api/native/project':return self.send(200,bridge.native.manage_project(body))
                    if self.path=='/api/native/stop-blender':return self.send(200,bridge.native.stop_blender())
                    if self.path=='/api/native/git':return self.send(200,bridge.native.project_git(**body))
                    if self.path=='/api/native/blender-cancel':return self.send(200,bridge.native.cancel_blender(**body))
                    if self.path=='/api/native/unity-start':return self.send(200,bridge.native.unity.start(**body))
                    if self.path=='/api/native/unity-stop':return self.send(200,bridge.native.unity.stop(**body))
                    return self.send(200,bridge.native.setup_privacy())
                if self.command=='POST' and self.path=='/api/import':
                    if self.headers.get('Origin')!='http://'+expected:return self.send(403,{'error':'Invalid origin'})
                    size=int(self.headers.get('Content-Length','0'))
                    if size<1 or size>4*1024**2:raise ValueError('Workflow is too large.')
                    if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Expected JSON.')
                    value=json.loads(self.rfile.read(size));workflow=validate_workflow(value['workflow'])
                    target=bridge.root/'workflows'/(workflow['id']+'.json')
                    if target.exists() and value.get('replace') is not True:raise ValueError('This id already exists. Choose another id or explicitly enable Replace.')
                    with bridge.lock:atomic_json(target,workflow)
                    return self.send(201,{'imported':workflow['id']})
                return self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError) as error:return self.send(400,{'error':str(error)[:500]})
        do_GET=handle_request
        do_POST=handle_request
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server

if __name__=='__main__':
    from bridge import Bridge
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(pathlib.Path(args.config).read_text(encoding='utf-8'));server=start_admin(Bridge(config))
    try:threading.Event().wait()
    finally:server.shutdown();server.server_close()
