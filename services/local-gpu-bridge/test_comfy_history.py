import unittest
from unittest.mock import Mock
from bridge import ComfyAdapter


class HistoryTests(unittest.TestCase):
    def test_completion_between_history_and_queue_is_not_unknown(self):
        adapter = ComfyAdapter('http://127.0.0.1:8188')
        history = {'id': {'status': {'completed': True, 'status_str': 'success'},
                          'outputs': {'2': {'audio': [{'filename': 'voice.flac', 'subfolder': 'audio', 'type': 'output'}]}}}}
        adapter.request = Mock(side_effect=[{}, {'queue_running': [], 'queue_pending': []}, history])
        result = adapter.inspect('id')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['artifacts'][0]['filename'], 'voice.flac')
        self.assertEqual(adapter.request.call_args_list[-1].args, ('/history/id',))

    def test_missing_history_stays_unknown_without_resubmission(self):
        adapter = ComfyAdapter('http://127.0.0.1:8188')
        adapter.request = Mock(side_effect=[{}, {'queue_running': [], 'queue_pending': []}, {}])
        self.assertEqual(adapter.inspect('id')['status'], 'unknown')
        self.assertEqual(adapter.request.call_count, 3)


if __name__ == '__main__':
    unittest.main()
