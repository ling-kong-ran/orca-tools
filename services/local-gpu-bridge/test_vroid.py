import base64, importlib.util, io, json, pathlib, struct, tempfile, unittest, unittest.mock, zlib
from native_control import NativeControl
from native_vroid import clean_png
from test_native_vrm import container


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

    def test_export_is_project_scoped_and_requires_explicit_metadata_and_overwrite(self):
        args = {'path': 'avatar.vrm', 'title': 'Avatar', 'author': 'Artist'}
        result = self.control.validate(self.project, 'export_vrm', args)
        self.assertEqual(result['format'], '1.0')
        self.assertEqual(result['path'], str(self.project/'avatar.vrm'))
        for bad in ({'path': '../outside.vrm'}, {'path': 'avatar.vroid'}, {'format': '2.0'},
                    {'title': ''}, {'author': 'a\ncontact'}, {'title': 'a'*201}, {'replace': 'true'}):
            with self.assertRaises(ValueError): self.control.validate(self.project, 'export_vrm', {**args, **bad})
        (self.project/'avatar.vrm').write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'replace=true'):
            self.control.validate(self.project, 'export_vrm', args)
        self.assertTrue(self.control.validate(self.project, 'export_vrm', {**args, 'replace': True})['replace'])

    def test_export_checks_container_and_returns_only_relative_file_receipt(self):
        args = {'path': 'avatar.vrm', 'title': 'Avatar', 'author': 'Artist'}
        reply = {'content': [{'type': 'text', 'text': '{"saved":true}'}]}
        with unittest.mock.patch.object(self.control, 'ensure_started'), unittest.mock.patch.object(self.control, 'rpc', return_value=reply) as rpc:
            with self.assertRaisesRegex(ValueError, 'produce'): self.control.call('test', 'export_vrm', args)
            (self.project/'avatar.vrm').write_bytes(b'corrupt')
            args['replace'] = True
            with self.assertRaisesRegex(ValueError, 'container'): self.control.call('test', 'export_vrm', args)
            (self.project/'avatar.vrm').write_bytes(container())
            result = json.loads(self.control.call('test', 'export_vrm', args)['content'][0]['text'])
            self.assertTrue(result['saved']);self.assertEqual(result['path'],'avatar.vrm');self.assertEqual(result['format'],'1.0')
            self.assertEqual(result['license_preset'],'commercial_modifiable');self.assertTrue(result['license']['commercial_use'])
            self.assertNotIn(str(self.root), json.dumps(result))
            self.assertEqual(rpc.call_args.kwargs['timeout'], 285)

    def test_old_session_save_operation_uses_the_same_vrm_exporter(self):
        args = {'path': 'avatar.vrm', 'title': 'Avatar', 'author': 'Artist'}
        validated = self.control.validate(self.project, 'save', args)
        self.assertEqual(validated['format'], '1.0')
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', {'path': 'avatar.vrm'})
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', {**args, 'path': '../outside.vrm'})
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', {**args, 'path': 'source.vroid'})
        (self.project/'avatar.vrm').write_bytes(container())
        with self.assertRaises(ValueError): self.control.validate(self.project, 'save', args)
        reply = {'content': [{'type': 'text', 'text': '{"saved":true}'}]}
        with unittest.mock.patch.object(self.control, 'ensure_started'), unittest.mock.patch.object(self.control, 'rpc', return_value=reply) as rpc:
            result = self.control.call('test', 'save', {**args, 'replace': True})
            self.assertFalse(result['isError'])
            self.assertEqual(rpc.call_args.args[1]['name'], 'export_vrm')
            self.assertEqual(rpc.call_args.kwargs['timeout'], 285)

    def test_existing_license_update_needs_explicit_replace_but_does_not_start_studio(self):
        file=self.project/'avatar.vrm';file.write_bytes(container())
        with self.assertRaises(ValueError):self.control.call('test','set_vrm_license',{'path':'avatar.vrm'})
        with unittest.mock.patch.object(self.control,'ensure_started') as start:
            value=self.control.call('test','set_vrm_license',{'path':'avatar.vrm','replace':True})
            start.assert_not_called();self.assertTrue(json.loads(value['content'][0]['text'])['license']['modification'])

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


class VroidStateTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('vroid_state_client', pathlib.Path(__file__).parent/'plugin/client.py')
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.client = self.module.Client.__new__(self.module.Client)

    def state(self, state):
        reply = {'content': [{'type': 'text', 'text': json.dumps(state)}], 'isError': False}
        with unittest.mock.patch.object(self.client, 'request', return_value=reply):
            result = self.client.call('vroid_operation', {'project_id': 'test', 'operation': 'state'})
        return json.loads(result['content'][0]['text'])

    def test_running_editor_without_model_does_not_report_software_startup(self):
        value = self.state({'ready': False, 'updating': False, 'selectors': 0, 'in_edit': False, 'section': None})
        self.assertTrue(value['editor_connected']); self.assertFalse(value['model_ready'])
        self.assertEqual(value['phase'], 'awaiting_model'); self.assertNotIn('ready', value)
        self.assertIn('Call create', value['next_action']); self.assertIn('Do not wait', value['next_action'])

    def test_loading_updating_and_ready_models_remain_distinct(self):
        for ready, updating, expected in [(False, False, 'loading_model'), (False, True, 'updating_model'), (True, False, 'editing')]:
            value = self.state({'ready': ready, 'updating': updating, 'in_edit': True, 'selectors': 4})
            self.assertEqual(value['phase'], expected); self.assertEqual(value['model_ready'], ready)

    def test_status_queue_does_not_claim_model_is_ready(self):
        reply = {'content': [{'type': 'text', 'text': '{"queued":0}'}]}
        result = self.module.vroid_state_result(reply, 'status')
        value = json.loads(result['content'][0]['text'])
        self.assertTrue(value['editor_connected']); self.assertNotIn('model_ready', value)
        self.assertIn('Use state', value['next_action'])

    def test_error_responses_are_not_relabelled_as_connected(self):
        reply = {'content': [{'type': 'text', 'text': '{"ready":false,"in_edit":false}'}], 'isError': True}
        result = self.module.vroid_state_result(reply, 'state')
        self.assertNotIn('editor_connected', json.loads(result['content'][0]['text']))


if __name__ == '__main__': unittest.main()
