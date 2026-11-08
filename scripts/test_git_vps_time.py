import importlib.util,os,pathlib,subprocess,tempfile,unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('git_vps_time',pathlib.Path(__file__).with_name('git-vps-time.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class GitTimeTests(unittest.TestCase):
    def test_new_commit_contains_utc_offsets_even_with_local_zone_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
            git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'asset.txt').write_text('asset')
            git('add','asset.txt')
            with patch.dict(os.environ,{'TZ':'Asia/Shanghai'}):
                self.assertEqual(module.main(['-C',str(root),'commit','-qm','fixture']),0)
            self.assertEqual(git('log','-1','--format=%ai|%ci').count('+0000'),2)
            self.assertEqual(git('status','--porcelain'),'')
            with patch.dict(os.environ,{'GIT_AUTHOR_DATE':'2026-11-01T01:30:00+08:00','GIT_COMMITTER_DATE':'2026-11-01T01:30:00+08:00'}):
                git('commit','--amend','--no-edit','--reset-author')
            instant=git('log','-1','--format=%at')
            self.assertEqual(module.main(['-C',str(root),'commit','--amend','--no-edit','-q']),0)
            self.assertEqual(git('log','-1','--format=%at'),instant)
            self.assertEqual(git('log','-1','--format=%ai|%ci').count('+0000'),2)
            self.assertEqual(module.main(['-C',str(root),'commit','--allow-empty','-qm','explicit','--date=2026-11-01T01:30:00+08:00']),0)
            self.assertIn(git('log','-1','--format=%aI'),('2026-10-31T17:30:00+00:00','2026-10-31T17:30:00Z'))

if __name__=='__main__':unittest.main()
