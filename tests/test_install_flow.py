import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from videopilot import pipeline,capcut
from videopilot.core import Settings,Job,UserError,Cancelled,atomic_json,read_json,file_hash,fingerprint
from test_system import PLAN,fixture,wav

class InstallFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job=Job.create(Settings(idea='install flow',duration=15,image_mode='manual',bgm='none',sfx=False),self.root/'projects')
        self.cancel=threading.Event();self.target=self.root/'target'/'draft_content.json'
        target=fixture(self.target);target['tracks']=[];atomic_json(self.target,target)
        self.original=self.target.read_bytes()
    def tearDown(self):self.tmp.cleanup()

    def voice(self,job,plan,speed,cancel,log):
        paths=[job.folder/'audio'/f'{i}.wav' for i in (1,2)]
        for path in paths:wav(path,7.5)
        return paths,[7.5,7.5]

    def test_attached_sample_builds_and_installs_using_existing_narration(self):
        atomic_json(self.job.folder/'script.json',PLAN)
        with patch.object(pipeline,'synthesize',side_effect=self.voice) as voice:
            pipeline.run(self.job,self.cancel,lambda _:None)
            source=self.root/'import';source.mkdir()
            for shot in read_json(self.job.folder/'timeline.json')['shots']:
                Image.new('RGB',(576,1024),'navy').save(source/f'{shot["id"]}.png')
            pipeline.import_images(self.job,source)
            pipeline.run(self.job,self.cancel,lambda _:None)
            self.assertEqual(self.job.data['state'],'NEEDS_CAPCUT_TEMPLATE')
            # Reproduce an old project prepared before its template was attached.
            self.job.data['prepared_signature']=fingerprint([PLAN,vars(self.job.settings)])
            template=self.root/'sample'/'draft_content.json';fixture(template)
            self.job.settings.template_path=str(template)
            self.job.status('TEMPLATE_ATTACHED','Sample attached.')
            before=file_hash(self.job.folder/'audio/narration.wav')
            with patch.object(capcut,'capcut_running',return_value=False):
                pipeline.build_and_install(self.job,self.target,self.cancel,lambda _:None)
            self.assertEqual(voice.call_count,1)
            self.assertEqual(file_hash(self.job.folder/'audio/narration.wav'),before)
        self.assertEqual(self.job.data['state'],'AWAITING_REVIEW')
        self.assertTrue(read_json(self.target)['tracks'])
        self.assertEqual(Path(self.job.data['backup_path']).read_bytes(),self.original)

    def test_incomplete_build_reports_next_step_and_never_installs(self):
        def wait(*args):self.job.status('WAITING_FOR_FLOW','3 shots still need images.')
        with patch.object(pipeline,'run',side_effect=wait),patch.object(capcut,'install') as install:
            with self.assertRaisesRegex(UserError,'3 shots still need images'):
                pipeline.build_and_install(self.job,self.target,self.cancel,lambda _:None)
            install.assert_not_called()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_cancel_during_build_never_installs(self):
        def stop(*args):self.cancel.set();self.job.status('STOPPED','Stopped.')
        with patch.object(pipeline,'run',side_effect=stop),patch.object(capcut,'install') as install:
            with self.assertRaises(Cancelled):pipeline.build_and_install(self.job,self.target,self.cancel,lambda _:None)
            install.assert_not_called()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_failed_build_keeps_destination_untouched(self):
        with patch.object(pipeline,'run',side_effect=UserError('Invalid template')),patch.object(capcut,'install') as install:
            with self.assertRaisesRegex(UserError,'Invalid template'):
                pipeline.build_and_install(self.job,self.target,self.cancel,lambda _:None)
            install.assert_not_called()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_ready_draft_installs_without_rebuilding(self):
        atomic_json(self.job.folder/'capcut/draft_content.json',{})
        self.job.status('READY_FOR_CAPCUT','Ready.')
        with patch.object(pipeline,'run') as build,patch.object(capcut,'install') as install:
            pipeline.build_and_install(self.job,self.target,self.cancel,lambda _:None)
            build.assert_not_called();install.assert_called_once_with(self.job,self.target)

    def test_template_change_does_not_invalidate_preparation_but_speed_does(self):
        original=copy.deepcopy(self.job.settings)
        signature=pipeline.preparation_signature(PLAN,original)
        self.job.settings.template_path='another/sample/draft_content.json'
        self.assertTrue(pipeline.preparation_matches(signature,PLAN,self.job.settings))
        self.job.settings.speed=1.1
        self.assertFalse(pipeline.preparation_matches(signature,PLAN,self.job.settings))
        self.assertFalse(pipeline.preparation_matches(fingerprint([PLAN,vars(original)]),PLAN,self.job.settings))

if __name__=='__main__':unittest.main()
