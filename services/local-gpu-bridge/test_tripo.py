import base64, json, pathlib, sys, tempfile, textwrap, unittest, unittest.mock
import native_tripo
from native_tripo import TripoControl, REGIONS

FAKE_MCP = textwrap.dedent('''
    import json, sys
    tools = [{"name": n, "inputSchema": {"type": "object"}} for n in
             ("tripo_get_status", "tripo_start_workflow", "tripo_set_account", "tripo_clear_account", "tripo_open_gallery")]
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg: continue
        if msg["method"] == "initialize": result = {"serverInfo": {"name": "fake"}}
        elif msg["method"] == "tools/list": result = {"tools": tools}
        else: result = {"content": [{"type": "text", "text": json.dumps(msg["params"]["arguments"])}], "isError": False}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
''')

SERVER = '\n'.join(['var STUDIO_ORIGIN = "https://studio.tripo3d.ai";', 'var STUDIO_API_BASE_URL = "https://api.tripo3d.ai";',
                    'return `TripoStudioMCP:${digest3}:studio.tripo3d.ai`;', 'var TRIPO_ACCOUNT_ORIGIN = "https://www.tripo3d.ai";',
                    'var TRIPO_MCP_HTTP_PORT = 32175;', 'var ALLOWED = ["tripo3d.ai", "tripo3d.com"];',
                    '`tripo-studio-global-server\\0${options2.identity ?? currentUserIdentity()}`',
                    'session2.status().authenticated || credentialStatus?.state === "available"',
                    'if ((options2.platform ?? process.platform) !== "win32") return new InteractionRequiredCredentialStore();'])


class TripoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.cache = self.root / 'cache'
        plugin = self.cache / '0.8.0' / 'mcp'; plugin.mkdir(parents=True)
        (plugin / 'server.mjs').write_text(SERVER, encoding='utf-8')
        (plugin / 'bootstrap.mjs').write_text('var TRIPO_MCP_HTTP_PORT = 32175;\n', encoding='utf-8')
        fake = self.root / 'fake_mcp.py'; fake.write_text(FAKE_MCP, encoding='utf-8')
        self.config = {'data_dir': str(self.root / 'bridge'), 'tripo': {'region': 'cn', 'plugin_cache': str(self.cache),
                       'data_dir': str(self.root / 'data'), 'asset_root': str(self.root / 'assets')}}
        self.control = TripoControl(self.config, command=[sys.executable, str(fake)])
        self.addCleanup(self.control.stop)

    def test_account_tools_stay_on_the_pc(self):
        listed = self.control.tools()
        names = [t['name'] for t in listed['tools']]
        self.assertEqual(names, ['tripo_get_status', 'tripo_start_workflow'])
        self.assertTrue(json.dumps(listed, ensure_ascii=False).isascii())
        self.assertNotIn('region', listed)
        for name in ('tripo_set_account', 'tripo_clear_account', 'tripo_open_gallery', 'shell', 'get_status'):
            with self.assertRaises(ValueError): self.control.call(name, {})

    def test_gallery_route_ids_resolve_to_downloadable_files(self):
        archive = self.control.roots['archive']; folder = archive / 'items/model_generation--one'
        folder.mkdir(parents=True); (folder / 'model-1.glb').write_bytes(b'glb')
        (archive / 'catalog.json').write_text(json.dumps({'items': {'model_generation--one': {
            'files': [{'file_id': 'model-1', 'relative_path': 'items/model_generation--one/model-1.glb'}]}}}))
        route = 'files/model_generation--one/model-1'
        result = json.loads(self.control.to_handles(json.dumps({'gallery_files': [route]})))
        handle = result['gallery_files'][0]
        self.assertEqual(handle, 'tripo:archive/items/model_generation--one/model-1.glb')
        self.assertEqual(self.control.file(handle).read_bytes(), b'glb')
        self.assertEqual(self.control.file('tripo:archive/' + route).read_bytes(), b'glb')
        nested = json.dumps({'text': json.dumps({'gallery_files': [route]})})
        self.assertEqual(json.loads(json.loads(self.control.to_handles(nested))['text'])['gallery_files'], [handle])
        with self.assertRaises(ValueError): self.control.file('tripo:archive/files/unknown/model-1')

    def test_paths_cross_as_handles(self):
        upload = self.control.upload('concept.png', base64.b64encode(b'png').decode())
        self.assertTrue(upload['path'].startswith('tripo:inputs/'))
        reply = self.control.call('tripo_start_workflow', {'steps': [{'source': {'image_path': upload['path']}}]})
        echoed = reply['content'][0]['text']
        self.assertIn(upload['path'], echoed); self.assertNotIn(str(self.root), echoed)
        local = self.control.to_local(upload['path'])
        self.assertEqual(pathlib.Path(local).read_bytes(), b'png')
        archive = self.root / 'data' / 'archive' / 'w1'; archive.mkdir(parents=True); (archive / 'model.glb').write_bytes(b'glb')
        text = self.control.to_handles(json.dumps({'file': str(archive / 'model.glb')}))
        self.assertEqual(json.loads(text)['file'], 'tripo:archive/w1/model.glb')
        nested = json.dumps({'text': json.dumps({'file': str(archive / 'model.glb'), 'dir': str(archive)})})
        inner = json.loads(json.loads(self.control.to_handles(nested))['text'])
        self.assertEqual(inner, {'file': 'tripo:archive/w1/model.glb', 'dir': 'tripo:archive/w1'})
        self.assertEqual(self.control.file('tripo:archive/w1/model.glb').read_bytes(), b'glb')
        for bad in ('tripo:inputs/../../secret.txt', 'tripo:archive/C:/Windows/win.ini', str(archive / 'model.glb'), 'tripo:other/x'):
            with self.assertRaises(ValueError): self.control.file(bad)
        for name in ('../x.png', 'run.exe', '.hidden.png', 'a b.png'):
            with self.assertRaises(ValueError): self.control.upload(name, base64.b64encode(b'x').decode())

    def test_china_copy_changes_only_the_site_settings(self):
        root = self.control.runtime_root()
        self.assertNotEqual(root, self.cache / '0.8.0')
        server = (root / 'mcp/server.mjs').read_text(encoding='utf-8')
        site = REGIONS['cn']
        for expected in (f'"{site["studio"]}"', f'"{site["api"]}"', f'"{site["account"]}"', ':studio.tripo3d.com`', 'PORT = 32176'):
            self.assertIn(expected, server)
        self.assertIn('["tripo3d.ai", "tripo3d.com"]', server)
        self.assertIn('orca-tripo-cn-server\\0${process.env.TRIPO_DATA_DIR}', server)
        self.assertIn('process.env.TRIPO_REUSE_BROWSER_SESSION === "1"', server)
        self.assertIn('32176', (root / 'mcp/bootstrap.mjs').read_text(encoding='utf-8'))
        self.assertIn('32175', (self.cache / '0.8.0/mcp/bootstrap.mjs').read_text(encoding='utf-8'))
        stamp = (root / '.bridge-patch.json').stat().st_mtime_ns
        self.assertEqual(self.control.runtime_root(), root)
        self.assertEqual((root / '.bridge-patch.json').stat().st_mtime_ns, stamp)
        env = self.control.environment()
        self.assertEqual(env['TRIPO_DATA_DIR'], str(self.root / 'data'))
        self.assertEqual(env['TRIPO_CHROME_CDP_URL'], 'http://127.0.0.1:9223')
        self.assertEqual(env['TRIPO_REUSE_BROWSER_SESSION'], '1')
        self.assertEqual(env['TRIPO_COOKIE_ONLY'],'1')

    def test_changed_plugin_is_refused_not_half_patched(self):
        newer = self.cache / '0.9.0' / 'mcp'; newer.mkdir(parents=True)
        (newer / 'server.mjs').write_text(SERVER.replace('var STUDIO_ORIGIN', 'const STUDIO_ORIGIN'), encoding='utf-8')
        (newer / 'bootstrap.mjs').write_text('var TRIPO_MCP_HTTP_PORT = 32175;\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'bridge update'): self.control.runtime_root()
        self.assertFalse((self.root / 'bridge/tripo/cn/0.9.0').exists())

    def test_global_region_runs_the_plugin_unchanged(self):
        control = TripoControl({**self.config, 'tripo': {**self.config['tripo'], 'region': 'global'}})
        self.assertEqual(control.runtime_root(), self.cache / '0.8.0')
        with self.assertRaises(ValueError): TripoControl({'tripo': {'region': 'eu'}})

    def test_login_profile_is_marked_for_the_plugin(self):
        profile = self.control.profile_dir()
        marker = json.loads((profile / native_tripo.MARKER).read_text(encoding='utf-8'))
        self.assertEqual(marker['schema_version'], 1); self.assertEqual(len(marker['ownership_token']), 43)
        self.assertEqual(self.control.profile_dir(), profile)

    def test_stopped_backend_restarts_and_repeats_only_reads(self):
        gone = {'content': [{'type': 'text', 'text': 'The Bootstrap could not connect to its local backend.'}], 'isError': True}
        fine = {'content': [{'type': 'text', 'text': '{}'}], 'isError': False}
        with unittest.mock.patch.object(self.control, '_call', side_effect=[gone, fine]) as call, unittest.mock.patch.object(self.control, 'stop') as stop:
            self.assertFalse(self.control.call('tripo_get_status', {})['isError'])
            self.assertEqual(call.call_count, 2); stop.assert_called_once()
        with unittest.mock.patch.object(self.control, '_call', side_effect=[gone, fine]) as call, unittest.mock.patch.object(self.control, 'stop') as stop:
            self.assertTrue(self.control.call('tripo_start_workflow', {})['isError'])
            self.assertEqual(call.call_count, 1); stop.assert_called_once()

    def test_descriptions_reach_the_vps_in_english(self):
        tool = native_tripo.english_tool({'name': 'tripo_get_status', 'description': '\u67e5\u770b\u72b6\u6001',
                                          'inputSchema': {'type': 'object', 'properties': {'page': {'type': 'integer', 'description': '\u9875\u7801'}}}})
        self.assertTrue(tool['description'].startswith('Show the Studio'))
        self.assertNotIn('description', tool['inputSchema']['properties']['page'])
        caps = {'operations': [{'name': 'model.generate', 'description': '\u751f\u6210', 'input_schema': {'title': '\u6a21\u578b', 'type': 'object'}}]}
        result = native_tripo.english_capabilities({'structuredContent': caps, 'content': [{'type': 'text', 'text': json.dumps(caps)}]})
        self.assertTrue(json.dumps(result, ensure_ascii=False).isascii())
        self.assertEqual(result['structuredContent']['operations'][0]['description'], native_tripo.OPERATION_TEXT['model.generate'])
        for name in native_tripo.TOOL_TEXT: self.assertTrue(native_tripo.TOOL_TEXT[name].isascii())

    def test_keepalive_waits_for_a_login(self):
        listed = self.control.tools()['tools']; self.control.stop()
        self.control.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.control.login_lock().write_text(str(__import__('os').getpid()), encoding='utf-8')
        self.assertTrue(self.control.login_active())
        with self.assertRaisesRegex(ValueError, 'sign-in is in progress'): self.control.call('tripo_get_status', {})
        self.assertEqual(self.control.tools()['tools'], listed)
        self.control.login_lock().write_text('999999999', encoding='utf-8')
        self.assertFalse(self.control.login_active()); self.assertFalse(self.control.login_lock().exists())

    def test_vps_client_lists_only_tripo_tools(self):
        sys.path.insert(0, str(pathlib.Path(__file__).parent / 'plugin'))
        import client
        fake = unittest.mock.Mock()
        fake.request.return_value = {'tools': [{'name': 'tripo_get_status'}, {'name': 'run_workflow'}, {'name': 'tripo_upload'}, 'bad']}
        names = [t['name'] for t in client.Client.tripo_tools(fake)]
        self.assertEqual(names, ['tripo_upload', 'tripo_download', 'tripo_get_status'])
        fake.request.side_effect = ValueError('offline')
        self.assertEqual([t['name'] for t in client.Client.tripo_tools(fake)], ['tripo_upload', 'tripo_download'])


if __name__ == '__main__':
    unittest.main()
