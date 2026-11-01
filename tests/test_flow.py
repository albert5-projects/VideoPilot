import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from videopilot.core import Job,Settings,atomic_json,read_json,make_timeline,UserError
from videopilot import flow,pipeline
from test_system import PLAN,fixture,wav

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job=Job.create(Settings(idea='Flow test',duration=15,flow_outputs=2),self.root/'projects')
        self.timeline=make_timeline(PLAN,[7.5,7.5],self.job.settings)
        atomic_json(self.job.folder/'timeline.json',self.timeline);self.queue=flow.queue_for(self.job,self.timeline)
        self.downloads=self.root/'Downloads';self.location=self.downloads/'VideoPilot'/self.queue['queue_id'];self.location.mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()
    def outputs(self,shot=None,complete=True,wrong_queue=False):
        shot=shot or self.timeline['shots'][0];variants=[]
        for i in (1,2):
            name=f'{shot["id"]}__v{i}.png';Image.new('RGB',(576,1024),'blue' if i==1 else 'red').save(self.location/name);variants.append({'filename':name,'width':576,'height':1024})
        atomic_json(self.location/f'{shot["id"]}.receipt.json',{'queue_id':'0'*24 if wrong_queue else self.queue['queue_id'],'shot_id':shot['id'],'complete':complete,'variants':variants})
    def test_queue_changes_when_prompt_or_count_changes(self):
        before=self.queue['queue_id'];self.job.settings.flow_outputs=1
        self.assertNotEqual(before,flow.queue_for(self.job,self.timeline)['queue_id'])
        self.job.settings.flow_outputs=2;self.timeline['shots'][0]['prompt']+=' different'
        self.assertNotEqual(before,flow.queue_for(self.job,self.timeline)['queue_id'])

    def test_shared_originals_keep_receipts_reimport_and_variant_changes_working(self):
        self.downloads=self.job.folder/'browser-downloads'
        self.location=self.downloads/'VideoPilot'/self.queue['queue_id'];self.location.mkdir(parents=True)
        self.outputs();shot=self.timeline['shots'][0]
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),1)
        source=self.location/f'{shot["id"]}__v1.png'
        variant=self.job.folder/'flow_variants'/shot['id']/'v1.png'
        self.assertTrue(source.samefile(variant));original=source.read_bytes()
        image=self.job.folder/'images'/f'{shot["id"]}.png'
        self.assertFalse(image.samefile(source))
        image.unlink();self.assertFalse(pipeline.cached_image(self.job,shot))
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),1)
        self.assertTrue(pipeline.cached_image(self.job,shot))
        flow.choose_variant(self.job,shot['id'],2)
        self.assertEqual(source.read_bytes(),original)
        replacement=source.with_suffix('.new.png');Image.new('RGB',(576,1024),'green').save(replacement);replacement.replace(source)
        self.assertEqual(variant.read_bytes(),original)
        image.unlink();self.assertEqual(flow.collect_downloads(self.job,self.downloads),1)
        self.assertTrue(source.samefile(variant));self.assertNotEqual(variant.read_bytes(),original)
    def test_receipt_needed_before_collection(self):
        self.outputs(complete=False);self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
        self.outputs(wrong_queue=True);self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
        self.outputs();self.assertEqual(flow.collect_downloads(self.job,self.downloads),1)
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
    def test_incomplete_corrupt_or_small_images_are_not_imported(self):
        self.outputs();shot=self.timeline['shots'][0]
        path=self.location/f'{shot["id"]}__v2.png';path.write_bytes(b'broken')
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
        Image.new('RGB',(288,512),'red').save(path)
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
    def test_targeted_import_leaves_other_completed_receipts_for_their_worker(self):
        first,second=self.timeline['shots'][:2]
        self.outputs(first);self.outputs(second)
        self.assertEqual(flow.collect_downloads(self.job,self.downloads,shot_ids={second['id']}),1)
        self.assertTrue(pipeline.cached_image(self.job,second));self.assertFalse(pipeline.cached_image(self.job,first))
    def test_path_traversal_in_receipt_rejected(self):
        self.outputs();shot=self.timeline['shots'][0];path=self.location/f'{shot["id"]}.receipt.json';data=read_json(path);data['variants'][0]['filename']='../../outside.png';atomic_json(path,data)
        self.assertEqual(flow.collect_downloads(self.job,self.downloads),0)
    def test_user_can_choose_variant_before_install(self):
        self.outputs();flow.collect_downloads(self.job,self.downloads);shot=self.timeline['shots'][0]
        flow.choose_variant(self.job,shot['id'],2)
        with Image.open(self.job.folder/'images'/f'{shot["id"]}.png') as im:self.assertEqual(im.getpixel((0,0)),(255,0,0))
        self.job.data['installed_path']='installed.json'
        with self.assertRaises(UserError):flow.choose_variant(self.job,shot['id'],1)
    def test_flow_resume_reuses_measured_audio(self):
        template=self.root/'template'/'draft_content.json';fixture(template)
        self.job.settings.template_path=str(template);self.job.settings.flow_downloads=str(self.downloads)
        atomic_json(self.job.folder/'script.json',PLAN)
        def voice(job,plan,speed,cancel,log):
            files=[job.folder/'audio'/f'{i:03d}.wav' for i in (1,2)]
            for p in files:wav(p,7.5)
            return files,[7.5,7.5]
        with patch('videopilot.pipeline.synthesize',side_effect=voice) as tts:
            pipeline.run(self.job,threading.Event(),lambda _:None)
            self.assertEqual(self.job.data['state'],'WAITING_FOR_FLOW')
            self.queue=read_json(self.job.folder/'FLOW_QUEUE.json');self.location=self.downloads/'VideoPilot'/self.queue['queue_id'];self.location.mkdir(parents=True,exist_ok=True)
            for shot in self.timeline['shots']:self.outputs(shot)
            pipeline.run(self.job,threading.Event(),lambda _:None)
            self.assertEqual(self.job.data['state'],'READY_FOR_CAPCUT');self.assertEqual(tts.call_count,1)
            self.assertFalse(read_json(self.job.folder/'validation.json')['rendered'])

if __name__=='__main__':unittest.main()
