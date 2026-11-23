import json
import unittest
from remote_privacy import remote_json, remote_text


class RemotePrivacyTests(unittest.TestCase):
    def test_unity_image_bytes_are_omitted_before_text_redaction(self):
        payload = 'A+/B' * 250_000
        reply = {'content':[{'type':'image','data':payload}, {'type':'text','text':
            json.dumps({'base64':payload,'message':'contact first.last+ops@example.test'})}]}
        result = remote_json(reply, omit_images=True)
        self.assertLess(len(json.dumps(result)), 200)
        self.assertEqual(json.loads(result['content'][1]['text']), {'message':'contact [email]'})
        self.assertEqual(remote_text(payload + ' at first.last+ops@example.test'), payload + ' at [email]')

    def test_hardware_metadata_is_removed_from_nested_unity_replies(self):
        private = {'graphicsDeviceName': 'NVIDIA GeForce RTX 2060',
                   'graphics_device_vendor': 'NVIDIA', 'graphicsDeviceID': 123,
                   'graphicsDeviceVendorID': 456, 'graphicsDeviceVersion': 'private driver',
                   'graphicsMemorySize': 32768, 'GPU': {'name': 'private model'},
                   'adapter_name': 'private adapter', 'systemInfo': {'renderer': 'private model'},
                   'scene': 'Assets/Game.unity', 'width': 1920, 'compilationFailed': False}
        result = remote_json({'structuredContent': private, 'content': [
            {'type': 'text', 'text': json.dumps(private)}]})
        expected = {'scene': 'Assets/Game.unity', 'width': 1920, 'compilationFailed': False}
        self.assertEqual(result['structuredContent'], expected)
        self.assertEqual(json.loads(result['content'][0]['text']), expected)
        # Text downloads bypass send_json, so native file filtering must apply
        # the same structured metadata policy before streaming the file.
        from native_control import private_result, private_text
        self.assertEqual(private_result(private), expected)
        self.assertEqual(json.loads(private_text(json.dumps(private))), expected)

    def test_hardware_models_and_diagnostic_lines_are_filtered(self):
        for model in ('NVIDIA GeForce RTX 2060', 'RTX 2060', 'AMD Radeon RX 6600',
                      'Intel Arc A770', 'NVIDIA A100'):
            result = remote_text('Renderer: '+model+'\nerror CS1002: ; expected')
            self.assertNotIn(model, result)
            self.assertIn('error CS1002: ; expected', result)
        result = remote_text('graphicsDeviceVendor: private-vendor\nGraphics Memory Size = 32768\nBuild complete')
        self.assertNotIn('private-vendor', result)
        self.assertNotIn('32768', result)
        self.assertIn('Build complete', result)
        safe = {'renderer': 'MeshRenderer', 'graphicsApi': 'Direct3D11', 'width': 1920,
                'height': 1080, 'samples': 16, 'hardware_render': True}
        self.assertEqual(remote_json(safe), safe)

    def test_schema_identifiers_survive_the_tripo_boundary(self):
        schema = {'$schema': 'http://json-schema.org/draft-07/schema#',
                  'type': 'object', 'properties': {'page': {'type': 'integer', 'minimum': 1}}}
        value = {'tools': [{'name': 'tripo_list_models', 'inputSchema': schema}]}
        self.assertEqual(remote_json(value, resources=True), value)
        self.assertEqual(json.loads(remote_json(json.dumps(schema), resources=True)), schema)
        for secret in ('https://private.example/schema?token=secret',
                       'http://json-schema.org/draft-07/schema#?secret', '[remote resource]'):
            filtered = remote_json({**schema, '$schema': secret}, resources=True)
            self.assertNotIn('$schema', filtered)
        self.assertNotIn('url', remote_json({'url': 'https://private.example/file?token=secret'}, resources=True))

    def test_plain_text_email_and_url_credentials_are_filtered(self):
        text=remote_text('Contact user+tag@example.com; https://alice:private-secret@localhost/file?access_token=private-token&ok=1')
        for forbidden in ('user+tag@example.com','alice','private-secret','private-token'):self.assertNotIn(forbidden,text)
        self.assertIn('ok=1',text)
    def test_nested_mcp_content_cannot_bypass_metadata_filter(self):
        private = {'region': 'cn', 'account_region': 'CN', 'locale': 'zh-CN',
                   'browser_locale': 'zh-CN', 'timezone': 'Asia/Shanghai',
                   'created_at': '2026-10-29T11:22:23+08:00', 'email': 'private@example.test',
                   'public_ip': '198.51.100.9', 'device_id': 'machine-secret',
                   'message': 'Upload at s3.bj.bcebos.com failed',
                   'url': 'https://studio.cdn.tripo3d.com/file?auth_key=secret'}
        response = remote_json({'structuredContent': private, 'content': [
            {'type': 'text', 'text': json.dumps(private)}]}, resources=True)
        encoded = json.dumps(response)
        for forbidden in ['Shanghai', 'zh-CN', '198.51.100.9', 'machine-secret',
                          'private@example.test', 'bcebos.com', 'tripo3d.com', 'auth_key', '+08:00']:
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(response['structuredContent']['created_at'], '2026-10-29T03:22:23Z')
        self.assertNotIn('timezone', response['structuredContent'])
        self.assertEqual(json.loads(response['content'][0]['text']), response['structuredContent'])

    def test_paths_errors_and_project_file_text_are_filtered(self):
        text = remote_text('Failed at C:\\Users\\Private\\log.txt\nAsia/Hong_Kong\n203.0.113.8\n2001:db8::8')
        for forbidden in ['Private', 'Hong_Kong', '203.0.113.8', '2001:db8']:
            self.assertNotIn(forbidden, text)

    def test_user_content_and_rendering_parameters_stay_usable(self):
        user = {'prompt': '中文角色，English voice', 'language': 'English',
                'region': {'x': 1, 'y': 2, 'width': 3}, 'model_version': 'v3.1-20260211',
                'path': 'tripo:archive/items/model-test/model.glb',
                'content': [{'type': 'image', 'data': 'abc123+/=', 'mimeType': 'image/png'}],
                'schema': {'enum': ['Chinese', 'English'], 'type': 'string'}}
        self.assertEqual(remote_json(user, resources=True), user)

    def test_ipv6_filter_does_not_damage_utc_or_model_ids(self):
        safe = {'time': '2026-10-29T03:22:23Z', 'sha256': 'a' * 64, 'id': '43bca2d0-4f3a-4e82-9511-c11a798f5b26'}
        self.assertEqual(remote_json(safe), safe)

    def test_error_messages_do_not_reveal_the_service_region(self):
        value = remote_json({'error': 'China-site storage failed; region cn needs an update.'}, resources=True)
        self.assertNotIn('China', value['error'])
        self.assertNotIn('region cn', value['error'])


if __name__ == '__main__': unittest.main()
