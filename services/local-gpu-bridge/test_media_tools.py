import json,pathlib,tempfile,types,unittest
from unittest.mock import Mock
from native_script import media_command,ProcessBroker

class MediaToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name);(self.root/'tools').mkdir()
        (self.root/'tools/cut.py').write_text('print("test")')
        (self.root/'tools/card.js').write_text('console.log("test")')
        settings={'root':str(self.root/'LocalGpuMedia'),'python_home':str(self.root/'python'),
                  'browsers_path':str(self.root/'browsers'),'project_ids':['approved']}
        settings.update({name+'_executable':str(self.root/'LocalGpuMedia'/(name+'.exe')) for name in ('python','node','ffmpeg','ffprobe','chromium')})
        self.control=types.SimpleNamespace(config={'native':{'media_tools':settings,'projects':[
            {'id':'approved','enabled':True,'allow_scripts':True}]}},guard=types.SimpleNamespace(require=Mock()))
        self.job={'project_id':'approved'}
    def test_fixed_interpreters_require_project_file_and_all_network_guards(self):
        for alias,file in [('python','cut.py'),('py','cut.py'),('python3','cut.py'),('node','card.js')]:
            exe,args,env=media_command(self.control,self.job,self.root,alias,['tools/'+file,'--test'])
            self.assertEqual(args,[str(self.root/'tools'/file),'--test'])
            self.assertTrue(env['PATH'].startswith(str(self.root/'LocalGpuMedia')))
            self.assertEqual(env['TZ'],'UTC')
        self.assertEqual(self.control.guard.require.call_count,20)
        for argv in [['-c','evil'],['-m','pip'],['../secret.py'],['tools/card.js'],[]]:
            with self.assertRaises(ValueError):media_command(self.control,self.job,self.root,'python',argv)
        self.assertIsNone(media_command(self.control,self.job,self.root,'powershell',[]))
    def test_opt_in_and_revocation(self):
        for field in ('enabled','allow_scripts'):
            project=self.control.config['native']['projects'][0];project[field]=False
            with self.assertRaises(ValueError):media_command(self.control,self.job,self.root,'python',['tools/cut.py'])
            project[field]=True
        self.control.config['native']['media_tools']['project_ids']=[]
        with self.assertRaises(ValueError):media_command(self.control,self.job,self.root,'ffmpeg',['-version'])
    def test_async_child_keeps_parent_deadline_responsive_and_reports_failure(self):
        state={'code':None}
        def factory(args,cwd,log,env,**options):
            self.assertEqual(options,{'process_limit':64})
            log.write_text('encoder diagnostic',encoding='utf-8')
            return types.SimpleNamespace(poll=lambda:state['code'],stop=Mock(),close=Mock())
        self.control.process_factory=factory
        broker=ProcessBroker(self.control,self.job,self.root,self.root)
        req=self.root/'1.request.json';req.write_text(json.dumps({'kind':'execute','data':{'executable':'python','args':['tools/cut.py']}}))
        broker.service();self.assertEqual(len(broker.pending),1)
        broker.service();self.assertFalse((self.root/'1.response.json').exists())
        state['code']=7;broker.service()
        self.assertEqual(json.loads((self.root/'1.response.json').read_text())['code'],7)
        self.assertEqual(broker.media_failures,1);self.assertFalse(broker.pending);broker.close()

    def test_staged_settings_load_only_for_a_new_control_instance(self):
        from native_control import NativeControl
        config={'data_dir':str(self.root/'state'),'native':{'projects':[]}}
        old=NativeControl(config)
        target=old.root/'media-tools.json';target.write_text(json.dumps({'project_ids':['approved']}))
        self.assertNotIn('media_tools',old.config['native'])
        new=NativeControl({'data_dir':config['data_dir'],'native':{'projects':[]}})
        self.assertEqual(new.config['native']['media_tools']['project_ids'],['approved'])

    def test_collected_video_can_be_downloaded_as_a_registered_artifact(self):
        from native_control import NativeControl
        import uuid
        control=NativeControl({'data_dir':str(self.root/'state'),'native':{'projects':[
            {'id':'approved','enabled':True,'root':str(self.root)}]}})
        ident=uuid.uuid4().hex;folder=control.root/'artifacts';folder.mkdir(exist_ok=True)
        for suffix in ('mp4','webm','wav','ogg'):
            file=folder/(ident+'-0.'+suffix);file.write_bytes(b'media')
            control.jobs[ident]={'project_id':'approved','status':'succeeded','artifacts':[{'file':file.name}]}
            self.assertEqual(control.artifact(ident,0),file)

if __name__=='__main__':unittest.main()
