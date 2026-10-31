import types,unittest
from unittest.mock import patch
from test_bridge import client_module

class NativeWaitTests(unittest.TestCase):
    def setUp(self):
        self.client=client_module.Client.__new__(client_module.Client);self.clock=0;self.calls=[]
        self.time=types.SimpleNamespace(monotonic=lambda:self.clock,sleep=self.sleep)
        self.patch=patch.object(client_module,'time',self.time);self.patch.start();self.addCleanup(self.patch.stop)
    def sleep(self,seconds):self.clock+=seconds
    def request(self,statuses):
        def call(route,timeout=None):
            self.calls.append((route,timeout));return {'id':'a'*32,'status':statuses.pop(0) if len(statuses)>1 else statuses[0]}
        self.client.request=call
    def test_completed_job_returns_immediately_without_sleep_or_submission(self):
        self.request(['succeeded']);value=self.client.call('wait_native_job',{'job_id':'a'*32})
        self.assertFalse(value['waiting']);self.assertEqual(self.clock,0);self.assertEqual(len(self.calls),1)
        self.assertTrue(all(route=='/v1/native/jobs/'+'a'*32 for route,_ in self.calls))
    def test_polling_stops_when_render_finishes(self):
        self.request(['queued','running','succeeded']);value=self.client.wait_native_job({'job_id':'a'*32})
        self.assertFalse(value['waiting']);self.assertEqual(value['job']['status'],'succeeded');self.assertEqual(self.clock,6)
    def test_deadline_returns_pending_without_cancelling_or_creating_a_task(self):
        self.request(['running']);value=self.client.wait_native_job({'job_id':'a'*32,'max_wait_seconds':5})
        self.assertTrue(value['waiting']);self.assertEqual(self.clock,5);self.assertIn('same job_id',value['next_action']);self.assertEqual(len(self.calls),2)
        self.assertEqual([t for _,t in self.calls],[5,2])
    def test_last_request_timeout_keeps_last_known_running_state(self):
        def request(route,timeout=None):
            if self.clock==0:return {'status':'running'}
            self.clock+=timeout;raise ValueError('timeout')
        self.client.request=request
        self.assertTrue(self.client.wait_native_job({'job_id':'a'*32,'max_wait_seconds':5})['waiting'])
        self.client.request=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('unreachable'))
        with self.assertRaisesRegex(ValueError,'unreachable'):self.client.wait_native_job({'job_id':'a'*32})
    def test_bad_ids_and_wait_values_are_rejected(self):
        for args in ({'job_id':'../x'},{'job_id':'a'*32,'max_wait_seconds':26},{'job_id':'a'*32,'max_wait_seconds':True},{'job_id':'a'*32,'other':1}):
            with self.assertRaises(ValueError):self.client.wait_native_job(args)

if __name__=='__main__':unittest.main()
