import concurrent.futures
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from job_reuse import latest_attempt
from native_control import NativeControl


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.project=self.root/'project';self.project.mkdir()
        self.config={'data_dir':str(self.root/'bridge'),'native':{'projects':[{'id':'game','name':'Game','root':str(self.project),'enabled':True,'git':{'enabled':True}}]}}
        self.body={'project_id':'game','engine':'git','operation':'fetch','arguments':{},'request_id':'a'*32}
        self.fingerprint=hashlib.sha256(json.dumps({k:self.body[k] for k in ('project_id','engine','operation','arguments')},sort_keys=True).encode()).hexdigest()

    def tearDown(self):self.temp.cleanup()

    def seed(self,control,ident,status,attempt=1,created=1):
        job={**{k:self.body[k] for k in self.body},'id':ident,'fingerprint':self.fingerprint,'status':status,'created_at':created,'artifacts':[],'attempt':attempt}
        control.jobs[ident]=job;control.save_job(job);return job

    def test_latest_attempt_ignores_load_order_and_checks_all_fingerprints(self):
        old={'id':'z','request_id':'a','fingerprint':'p','attempt':1,'created_at':100}
        new={'id':'a','request_id':'a','fingerprint':'p','attempt':2,'created_at':1}
        self.assertIs(latest_attempt({'a':new,'z':old},'a','p'),new)
        with self.assertRaises(ValueError):latest_attempt({'a':new,'z':{**old,'fingerprint':'different'}},'a','p')

    def test_nonfailed_requests_do_not_create_another_attempt(self):
        for status in ('queued','running','succeeded','unknown','cancelled'):
            control=NativeControl(self.config);control.jobs={}
            previous=self.seed(control,'b'*32,status)
            with patch.object(control,'run') as run:
                result=control.queue(self.body)
                self.assertEqual(result['id'],previous['id']);run.assert_not_called()
            with self.assertRaises(ValueError):control.queue({**self.body,'operation':'pull'})

    def test_failed_request_creates_one_retry_under_concurrent_submissions(self):
        control=NativeControl(self.config);old=self.seed(control,'b'*32,'failed');started=threading.Event();release=threading.Event();finished=threading.Event();calls=[]
        def execute(job):
            calls.append(job['id'])
            with control.lock:job['status']='running';control.save_job(job)
            started.set();release.wait(5)
            with control.lock:job['status']='succeeded';control.save_job(job)
            finished.set()
        with patch.object(control,'run',side_effect=execute):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    responses=list(pool.map(lambda _:control.queue(self.body),range(8)))
                self.assertTrue(started.wait(2));self.assertEqual(len({r['id'] for r in responses}),1)
                new=responses[0];self.assertNotEqual(new['id'],old['id']);self.assertEqual(new['retry_of'],old['id']);self.assertEqual(new['attempt'],2)
                self.assertEqual(len(calls),1);self.assertEqual(old['status'],'failed')
            finally:release.set();self.assertTrue(finished.wait(3))
            result=control.queue(self.body);self.assertEqual(result['id'],new['id']);self.assertEqual(result['status'],'succeeded')
        restored=NativeControl(self.config)
        with patch.object(restored,'run') as run:
            self.assertEqual(restored.queue(self.body)['id'],new['id']);run.assert_not_called()
        self.assertEqual(restored.jobs[old['id']]['status'],'failed')

    def test_retry_respects_admission_and_parameter_binding(self):
        control=NativeControl(self.config);old=self.seed(control,'b'*32,'failed')
        for i in range(8):control.jobs[str(i)]={'id':str(i),'request_id':str(i),'status':'running'}
        with patch.object(control,'run') as run:
            with self.assertRaisesRegex(ValueError,'full'):control.queue(self.body)
            with self.assertRaisesRegex(ValueError,'different'):control.queue({**self.body,'operation':'pull'})
            self.assertEqual(control.jobs[old['id']]['status'],'failed');run.assert_not_called()

    def test_restart_keeps_latest_uncertain_retry_without_restarting_old_failure(self):
        control=NativeControl(self.config)
        self.seed(control,'f'*32,'failed',attempt=1,created=10)
        self.seed(control,'0'*32,'running',attempt=2,created=20)
        restored=NativeControl(self.config)
        with patch.object(restored,'run') as run:
            result=restored.queue(self.body)
            self.assertEqual(result['id'],'0'*32);self.assertEqual(result['status'],'unknown');run.assert_not_called()


if __name__=='__main__':unittest.main()
