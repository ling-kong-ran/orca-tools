import unittest
from unittest.mock import Mock
from bridge import ComfyAdapter


class HistoryTests(unittest.TestCase):
    def test_windows_saved_audio_subfolders_are_normalized_and_deduplicated(self):
        adapter=ComfyAdapter('http://127.0.0.1:8188')
        files=[{'filename':'take.flac','subfolder':'audio\\StableAudio3_SFX','type':'output'},
               {'filename':'take.flac','subfolder':'audio/StableAudio3_SFX','type':'output'}]
        history={'id':{'status':{'completed':True},'outputs':{'11':{'audio':files}}}}
        result=adapter.history_status(history,'id')
        self.assertEqual(result['artifacts'],[{'filename':'take.flac','subfolder':'audio/StableAudio3_SFX','type':'output'}])

    def test_normalization_does_not_allow_absolute_paths_or_traversal(self):
        adapter=ComfyAdapter('http://127.0.0.1:8188')
        files=[{'filename':'take.flac','subfolder':folder,'type':'output'} for folder in ('..\\private','audio\\..\\private','C:\\private','\\\\server\\share','/private',None)]
        files += [{'filename':name,'subfolder':'audio','type':'output'} for name in ('..\\secret.flac','nested/file.flac','C:secret.flac')]
        files += [{'filename':'preview.flac','subfolder':'audio','type':'temp'}]
        history={'id':{'status':{'completed':True},'outputs':{'11':{'audio':files}}}}
        self.assertEqual(adapter.history_status(history,'id')['artifacts'],[])

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
