import importlib.util,io,pathlib,tempfile,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('transfer_client',pathlib.Path(__file__).parent/'plugin/client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


class TransferTimes(unittest.TestCase):
    def clock(self,zone):
        class ReceiverClock(datetime):
            def astimezone(self,tz=None):return super().astimezone(tz or zone)
        return patch.object(client,'datetime',ReceiverClock)

    def test_calendar_names_convert_same_instant_across_midnight(self):
        with self.clock(timezone.utc):
            for source,expected in [
                ('20261101-013000-shot.png','20261031-173000Z-shot.png'),
                ('shot_2026-11-01_01-30-00.png','shot_2026-10-31_17-30-00Z.png'),
                ('shot_2026-11-01T01:30:00+08:00.png','shot_2026-10-31T17:30:00Z.png'),
                ('shot_2026-11-01T01:30:00.123+08:00.png','shot_2026-10-31T17:30:00.123Z.png'),
                ('shot_2026-11-01T01:30:00Z.png','shot_2026-11-01T01:30:00Z.png'),
                ('asset-v3.1-20260211.glb','asset-v3.1-20260211.glb'),
                ('20261399-999999.png','20261399-999999.png')]:
                self.assertEqual(client.receiver_filename(source),expected)
                self.assertEqual(client.receiver_filename(expected),expected)

    def test_receiver_does_not_assume_every_timezone_is_eight_hours_away(self):
        with self.clock(timezone(timedelta(hours=5,minutes=45))):
            self.assertEqual(client.receiver_filename('20261101-013000.png'),'20261031-231500+0545.png')

    def test_all_download_routes_use_vps_names_and_keep_source_handles(self):
        class Response(io.BytesIO):
            headers={'Content-Length':'4'}
        with tempfile.TemporaryDirectory() as directory,self.clock(timezone.utc):
            folder=pathlib.Path(directory);instance=object.__new__(client.Client)
            requests=[]
            def request(route,*args,**kwargs):
                requests.append(route)
                if '/jobs/' in route:return {'status':'succeeded','artifacts':[{'index':0,'filename':'20261101-013000.png'}]}
                return Response(b'data')
            instance.request=request
            for tool in ('fetch_artifact','fetch_native_artifact','download_project_file','tripo_download'):
                args={'destination_dir':str(folder),'job_id':'a'*32,'index':0,'project_id':'test',
                      'path':'tripo:archive/20261101-013000.png' if tool=='tripo_download' else 'shots/20261101-013000.png'}
                result=instance.call(tool,args)
                self.assertIn('20261031-173000',pathlib.Path(result['path']).name)
                self.assertEqual(pathlib.Path(result['path']).read_bytes(),b'data')
                self.assertEqual(result['timestamp_source'],'receiver')
            self.assertTrue(any('20261101-013000' in route for route in requests))


if __name__=='__main__':unittest.main()
