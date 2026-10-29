import json
import unittest
from remote_privacy import remote_json, remote_text


class RemotePrivacyTests(unittest.TestCase):
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
