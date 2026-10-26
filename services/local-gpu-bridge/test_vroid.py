import base64, importlib.util, io, json, pathlib, struct, tempfile, unittest, unittest.mock, zlib
from native_control import NativeControl
from native_vroid import clean_png


def png():
    def chunk(kind, value):
        return struct.pack('>I', len(value))+kind+value+struct.pack('>I', zlib.crc32(kind+value))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))+chunk(b'tEXt', b'Host\x00private-device')+chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00'))+chunk(b'IEND', b'')


class VroidTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name); self.project = self.root/'project'; self.project.mkdir()
        self.native = NativeControl({'data_dir': str(self.root), 'native': {'projects': [{'id': 'test', 'name': 'Test', 'enabled': True, 'root': str(self.project)}]}})
        self.control = self.native.vroid

    def test_project_paths_and_explicit_overwrite(self):
        file = self.project/'avatar.vroid'; file.write_bytes(b'character')
        self.assertEqual(self.control.validate(self.project, 'open', {'path': 'avatar.vroid'})['path'], str(file))
        for path in ('../other.vroid', 'C:/other.vroid', '/other.vroid', 'avatar.exe'):
            with self.assertRaises(ValueError): self.control.validate(self.project, 'open', {'path': path})
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', {})
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', {'path': 'avatar.vroid'})
        self.assertNotIn('replace', self.control.validate(self.project, 'save', {'path': 'avatar.vroid', 'replace': True}))

    def test_raw_commands_and_ui_screenshots_are_not_forwarded(self):
        for operation, args in [('batch', {'operations': []}), ('ui_screenshot', {}), ('shell', {}), ('camera', {'action': 'probe'}), ('screenshot', {'mode': 'both'}), ('main_menu', {})]:
            with self.assertRaises(ValueError): self.control.validate(self.project, operation, args)
        with self.assertRaises(ValueError): self.control.call('disabled', 'state')
        self.assertEqual(self.control.validate(self.project, 'main_menu', {'discard_changes': True}), {})

    def test_parameter_paths_use_the_upstream_index_string_argument(self):
        args = {'section': 'Face', 'category': 'Irises', 'path': 'Face/Irises/Both Eyes', 'value': '#33AA77'}
        value = self.control.validate(self.project, 'set_param', args)
        self.assertEqual(value['index'], args['path']); self.assertNotIn('path', value)
        with self.assertRaises(ValueError): self.control.validate(self.project, 'set_param', {**args, 'index': 1})

    def test_privacy_filter_keeps_model_pixels_drops_metadata(self):
        result = self.control.filtered({'content': [
            {'type': 'text', 'text': json.dumps({'hardware': 'secret', 'ip': '1.2.3.4', 'name': 'Avatar', 'result': r'C:\private\avatar.vroid'})},
            {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(png()).decode()},
            {'type': 'resource', 'uri': 'file:///private'},
        ]})
        text = result['content'][0]['text']; self.assertIn('Avatar', text)
        self.assertNotIn('secret', text); self.assertNotIn('1.2.3.4', text); self.assertNotIn('C:', text)
        image = base64.b64decode(result['content'][1]['data'])
        self.assertNotIn(b'private-device', image); self.assertIn(b'IDAT', image)
        self.assertEqual(len(result['content']), 2)
        with self.assertRaises(ValueError): clean_png(base64.b64encode(b'not png').decode())

    def test_busy_edits_are_not_repeated_and_status_can_probe(self):
        reply = {'content': [{'type': 'text', 'text': 'ready'}]}
        with unittest.mock.patch.object(self.control, 'ensure_started'), unittest.mock.patch.object(self.control, 'rpc', return_value=reply) as rpc:
            self.control.lock.acquire()
            try:
                with self.assertRaisesRegex(ValueError, 'busy'): self.control.call('test', 'create', {'gender': 'female'})
                self.control.call('test', 'status')
                self.assertEqual(rpc.call_count, 1)
            finally: self.control.lock.release()

    def test_does_not_attach_to_an_unrelated_loopback_service(self):
        self.native.process_factory = unittest.mock.Mock()
        with unittest.mock.patch.object(self.native.guard, 'require'), unittest.mock.patch.object(self.control, 'settings_ready', return_value=True), unittest.mock.patch('native_vroid.socket.socket') as probe:
            probe.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaisesRegex(ValueError, 'occupied'): self.control.ensure_started()
        self.native.process_factory.assert_not_called()

    def test_timeout_has_filtered_error_and_never_retries(self):
        with unittest.mock.patch.object(self.control, 'ensure_started'), unittest.mock.patch.object(self.control, 'rpc', side_effect=TimeoutError('private-host')) as rpc:
            with self.assertLogs(level='ERROR'), self.assertRaisesRegex(ValueError, 'Query status'): self.control.call('test', 'state')
            self.assertEqual(rpc.call_count, 1)

    def test_mcp_preserves_inline_images_instead_of_stringifying_them(self):
        spec = importlib.util.spec_from_file_location('vroid_client', pathlib.Path(__file__).parent/'plugin/client.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        request = {'id': 2, 'method': 'tools/call', 'params': {'name': 'vroid_operation', 'arguments': {'project_id': 'test', 'operation': 'screenshot'}}}
        stream = unittest.mock.Mock(buffer=io.BytesIO((json.dumps(request)+'\n').encode()))
        reply = self.control.filtered({'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(png()).decode()}]})
        fake = unittest.mock.Mock(); fake.call.return_value = reply
        output = io.StringIO()
        with unittest.mock.patch.object(module.sys, 'stdin', stream), unittest.mock.patch.object(module.sys, 'stdout', output):
            module.serve(fake, module.VROID_TOOLS)
        result = json.loads(output.getvalue())['result']
        self.assertEqual(result['content'][0]['type'], 'image')
        self.assertFalse(result['isError'])


if __name__ == '__main__': unittest.main()
