import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import private_relay


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.seen = []
        seen = self.seen

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                if self.path == '/v1/redirect':
                    self.send_response(302); self.send_header('Location', 'http://example.invalid/'); self.end_headers(); return
                data = b'gpu-response'
                self.send_response(200); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        config_path = Path(self.temp.name)/'upstream.json'
        config_path.write_text(json.dumps({'listen':'127.0.0.1', 'port':self.upstream.server_port, 'token':'upstream-secret'}))
        self.config = {'listen':'10.0.0.1','peer':'127.0.0.1','port':18775,'token':'v'*48,'bridge_config':str(config_path)}
        with patch.object(private_relay, 'validate'):
            self.server = private_relay.Server(('127.0.0.1',0), private_relay.handler(self.config))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        for server in (self.server, self.upstream):
            server.shutdown(); server.server_close()
        self.temp.cleanup()

    def request(self, path='/v1/status', token=None, extra=None):
        headers={'Authorization':'Bearer '+(token or self.config['token']), **(extra or {})}
        req=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path, headers=headers)
        try:
            with self.opener.open(req,timeout=3) as response:return response.status,response.read()
        except urllib.error.HTTPError as e:
            with e:return e.code,e.read()

    def test_forward_replaces_credential_and_preserves_response(self):
        self.assertEqual(self.request(),(200,b'gpu-response'))
        self.assertEqual(self.seen,['Bearer upstream-secret'])

    def test_responses_do_not_disclose_server_version_or_date(self):
        req=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}/v1/status',
                                   headers={'Authorization':'Bearer '+self.config['token']})
        with self.opener.open(req,timeout=3) as response:
            self.assertIsNone(response.headers.get('Server'))
            self.assertIsNone(response.headers.get('Date'))
            response.read()

    def test_mcp_client_does_not_follow_redirects_or_repeat_credentials(self):
        spec=importlib.util.spec_from_file_location('redirect_client',Path(__file__).parent/'plugin/client.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        target=Path(self.temp.name)/'mcp.json'
        target.write_text(json.dumps({'url':f'http://127.0.0.1:{self.upstream.server_port}','token':'x'*40}))
        client=module.Client(target)
        with self.assertRaisesRegex(ValueError,'redirects are not allowed'):
            client.request('/v1/redirect')
        self.assertEqual(self.seen,['Bearer '+'x'*40])

    def test_rejects_wrong_token_peer_origin_and_admin(self):
        self.assertEqual(self.request(token='wrong')[0],403)
        self.assertEqual(self.request(extra={'Origin':'http://example.invalid'})[0],403)
        self.assertEqual(self.request('/api/config')[0],404)
        self.config['peer']='10.0.0.2'
        self.assertEqual(self.request()[0],403)
        self.assertEqual(self.seen,[])

    def test_no_redirect_following(self):
        status,body=self.request('/v1/redirect')
        self.assertEqual(status,502)
        self.assertNotIn(b'example.invalid',body)

    def test_private_addresses_only(self):
        for host in ('0.0.0.0','127.0.0.1','8.8.8.8','169.254.1.1','::1'):
            with self.assertRaises(ValueError):private_relay.private_ip(host)
        self.assertEqual(private_relay.private_ip('10.20.0.1'),'10.20.0.1')


class ClientPinTests(unittest.TestCase):
    def test_explicit_matching_private_pin_required(self):
        spec=importlib.util.spec_from_file_location('desktop_client',Path(__file__).parent/'plugin/client.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'client.json'
            def load(url,pin=None):
                target.write_text(json.dumps({'url':url,'token':'x'*40,'private_network_peer':pin}))
                return module.Client(target)
            with self.assertRaises(ValueError):load('http://10.20.0.1:18775')
            with self.assertRaises(ValueError):load('http://10.20.0.1:18775','10.20.0.2')
            with self.assertRaises(ValueError):load('http://8.8.8.8:18775','8.8.8.8')
            with self.assertRaises(ValueError):load('http://10.20.0.1:18775/path','10.20.0.1')
            self.assertEqual(load('http://10.20.0.1:18775','10.20.0.1').base,'http://10.20.0.1:18775')
            self.assertEqual(load('http://100.64.0.1:18775').base,'http://100.64.0.1:18775')


class DesktopInstallTests(unittest.TestCase):
    def test_new_store_location_takes_priority_over_stale_virtualized_path(self):
        path=Path(__file__).resolve().parents[2]/'scripts/install-claude-desktop-gpu.py'
        spec=importlib.util.spec_from_file_location('desktop_paths',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            local=Path(folder)/'Local'; roaming=Path(folder)/'Roaming'
            current=local/'Claude-Data/claude_example'
            current.mkdir(parents=True);(current/'config.json').write_text('{}')
            (local/'Packages/Claude_example/LocalCache/Roaming/Claude').mkdir(parents=True)
            with patch.dict(module.os.environ,{'LOCALAPPDATA':str(local),'APPDATA':str(roaming)}):
                self.assertEqual(module.desktop_configs(),[current])

    def test_preserves_existing_settings_and_does_not_embed_credentials(self):
        path=Path(__file__).resolve().parents[2]/'scripts/install-claude-desktop-gpu.py'
        spec=importlib.util.spec_from_file_location('desktop_installer',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original={'preferences':{'theme':'dark'},'mcpServers':{'other':{'command':'existing'}}}
        merged=module.merged_config(original,Path('C:/Private/Gpu'),Path('C:/Python/python.exe'))
        self.assertEqual(merged['mcpServers']['other'],original['mcpServers']['other'])
        self.assertEqual(merged['preferences'],original['preferences'])
        self.assertEqual(len(merged['mcpServers']),7)
        self.assertEqual(len(original['mcpServers']),1)
        for name,value in merged['mcpServers'].items():
            if name.startswith('orca-'):
                self.assertIn('--config',value['args'])
                self.assertEqual(value['env'],{'PYTHONUTF8':'1'})


if __name__ == '__main__':unittest.main()
