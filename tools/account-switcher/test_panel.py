import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

path=Path(__file__).resolve().parent/'panel/server.py'
spec=importlib.util.spec_from_file_location('panel_server',path)
panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)

class Fake:
    active='a'
    calls=[]
    def state(self):
        return {'activeAccountId':self.active,'accounts':[{'id':'a','email':'first@example.com'},{'id':'b','email':'second@example.com'}]}
    def select(self,account_id):
        self.calls.append(account_id);self.active=account_id

backend=Fake()
server=ThreadingHTTPServer(('127.0.0.1',0),None)
port=server.server_address[1]
server.RequestHandlerClass=panel.make_handler(backend,port)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
origin=f'http://127.0.0.1:{port}'

def request(route,payload=None,headers=None):
    h={'X-Panel-Token':panel.TOKEN,'Origin':origin,'Content-Type':'application/json'}
    if headers:h.update(headers)
    req=urllib.request.Request(origin+route,data=json.dumps(payload).encode() if payload is not None else None,headers=h)
    try:
        with urllib.request.urlopen(req,timeout=5) as r:return r.status,r.read()
    except urllib.error.HTTPError as e:return e.code,e.read()

try:
    code,html=request('/')
    assert code==200 and 'Claude Accounts'.encode() in html and b'__PANEL_TOKEN__' not in html
    code,body=request('/api/accounts');state=json.loads(body)
    assert code==200 and state['activeAccountId']=='a'
    assert set(state['accounts'][0])=={'id','email','current','usage','needsSignIn'}
    assert request('/api/accounts',headers={'X-Panel-Token':'bad'})[0]==403
    assert request('/api/accounts',headers={'Host':'foreign.invalid'})[0]==403
    assert request('/api/select',{'accountId':'b','expectedActiveAccountId':'a'},headers={'Origin':'https://foreign.invalid'})[0]==403
    assert request('/api/select',{'accountId':'missing','expectedActiveAccountId':'a'})[0]==400
    assert request('/api/select',{'accountId':'b','expectedActiveAccountId':None})[0]==409
    assert backend.calls==[]
    assert request('/api/select',{'accountId':'a','expectedActiveAccountId':'a'})[0]==200
    assert backend.calls==[]
    code,body=request('/api/select',{'accountId':'b','expectedActiveAccountId':'a'})
    assert code==200 and json.loads(body)['activeAccountId']=='b' and backend.calls==['b']
    print('PASS: live HTTP test covers account display, switching and confirmation, stale selection, no-op, invalid ID, session token, Host and Origin checks.')
finally:
    server.shutdown();server.server_close()
