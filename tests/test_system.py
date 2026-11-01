import copy, json, os, tempfile, threading, unittest, wave
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Settings, Job, UserError, atomic_json, read_json, make_timeline, validate_plan
from videopilot.audio import join_wavs, wav_info
from videopilot.capcut import Template, install, restore, mark_finished
from videopilot import pipeline

PLAN={'title':'A small test','visual_bible':'Cool blue documentary lighting, consistent explorer.', 'fact_check_notes':[],
      'scenes':[{'narration':'A quiet room holds a surprising secret waiting to be discovered.','visual':'A blue room','overlay':'Look closer','sfx':False},
                {'narration':'Follow the trail and the final clue becomes clear at last.','visual':'A golden key','overlay':'The final clue','sfx':True}]}

def wav(path,seconds,rate=24000):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as f:
        f.setparams((1,2,rate,0,'NONE','not compressed')); f.writeframes(b'\0\0'*round(seconds*rate))

def fixture(path):
    materials={'videos':[{'id':'v','type':'photo','path':'sample.png','duration':5000000,'width':1920,'height':1080}],
               'audios':[{'id':'a','type':'extract_music','path':'sample.wav','duration':5000000}],
               'texts':[{'id':'t','type':'text','content':json.dumps({'text':'Sample','styles':[{'range':[0,6],'size':8}]})}],
               'speeds':[{'id':'speed','speed':1.0}], 'effects':[],'transitions':[]}
    tracks=[]
    for kind,mid in [('video','v'),('audio','a'),('text','t')]:
        tracks.append({'id':kind,'type':kind,'segments':[{'id':kind+'-segment','material_id':mid,'extra_material_refs':['speed'],
            'target_timerange':{'start':0,'duration':5000000},'source_timerange':{'start':0,'duration':5000000},
            'speed':1.0,'volume':1.0,'clip':{'transform':{'x':0.,'y':-.6}},'common_keyframes':[]}]})
    d={'id':'template','version':360000,'duration':5000000,'canvas_config':{'width':1920,'height':1080,'ratio':'16:9'},'tracks':tracks,'materials':materials}
    atomic_json(path,d); return d

class TestSystem(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.settings=Settings(idea='Test idea',duration=15,shot_seconds=6,bgm='ambient',image_mode='manual')
        self.job=Job.create(self.settings,self.root/'projects'); self.cancel=threading.Event()
    def tearDown(self): self.tmp.cleanup()
    def media(self,timeline):
        from PIL import Image
        (self.job.folder/'images').mkdir(exist_ok=True)
        for s in timeline['shots']: Image.new('RGB',self.settings.dimensions,'navy').save(self.job.folder/'images'/f'{s["id"]}.png')
        for name,seconds in [('narration',15),('music',15),('whoosh',.28)]: wav(self.job.folder/'audio'/f'{name}.wav',seconds)
    def draft(self):
        template=self.root/'template'/'draft_content.json'; fixture(template)
        self.job.settings.template_path=str(template)
        timeline=make_timeline(PLAN,[7.5,7.5],self.settings); self.media(timeline)
        draft=Template(template).build(timeline,self.job.folder,self.settings)
        atomic_json(self.job.folder/'capcut'/'draft_content.json',draft)
        self.job.status('READY_FOR_CAPCUT','Ready'); return draft
    def test_timing_covers_audio_without_gaps(self):
        t=make_timeline(PLAN,[7.123456,9.876544],self.settings)
        self.assertEqual(t['duration'],17000000)
        end=0
        for shot in t['shots']:
            self.assertEqual(shot['start'],end); self.assertLessEqual(shot['duration'],6000000); end+=shot['duration']
        self.assertEqual(end,t['duration'])
        end=0
        for c in t['captions']: self.assertEqual(c['start'],end); end+=c['duration']
        self.assertEqual(end,t['duration'])
    def test_reject_invalid_brief(self):
        for key,value in [('duration',0),('shot_seconds',121),('aspect','bad'),('speed',float('nan')),('image_model','../bad')]:
            s=copy.deepcopy(self.settings); setattr(s,key,value)
            with self.assertRaises(UserError): s.validate()
    def test_no_silent_tts_truncation_in_plan_validation(self):
        p=copy.deepcopy(PLAN); p['scenes'][0]['narration']='a'*601
        with self.assertRaises(UserError): validate_plan(p)
    def test_join_audio_preserves_all_frames(self):
        a=self.root/'a.wav'; b=self.root/'b.wav'; out=self.root/'out.wav'; wav(a,.25); wav(b,.5)
        join_wavs([a,b],out); self.assertEqual(wav_info(out)['frames'],18000)
    def test_clone_remaps_all_material_references(self):
        d=self.draft(); materials=[m for v in d['materials'].values() for m in v]; ids=[m['id'] for m in materials]
        self.assertEqual(len(ids),len(set(ids)))
        for t in d['tracks']:
            for s in t['segments']:
                self.assertIn(s['material_id'],ids)
                for ref in s.get('extra_material_refs',[]): self.assertIn(ref,ids)
        self.assertEqual(d['canvas_config']['width'],1080)
        self.assertTrue(any(t['type']=='text' for t in d['tracks']))
    def test_template_untouched_and_existing_project_refused(self):
        self.draft(); template=Path(self.job.settings.template_path); before=template.read_bytes()
        target=self.root/'target'/'draft_content.json'; fixture(target); original=target.read_bytes()
        with patch('videopilot.capcut.capcut_running',return_value=False),self.assertRaises(UserError): install(self.job,target)
        self.assertEqual(original,target.read_bytes()); self.assertEqual(before,template.read_bytes())
    def test_install_backup_restore_and_finish_gates(self):
        self.draft(); target=self.root/'target'/'draft_content.json'; d=fixture(target); d['id']='registered-target'; d['tracks']=[]; atomic_json(target,d)
        original=read_json(target)
        with self.assertRaises(UserError): mark_finished(self.job)
        with patch('videopilot.capcut.capcut_running',return_value=False):
            install(self.job,target)
            self.assertEqual(read_json(target)['id'],'registered-target')
            self.assertEqual(self.job.data['state'],'AWAITING_REVIEW')
            self.assertEqual(read_json(self.job.data['backup_path']),original)
            with self.assertRaises(UserError): self.job.require_mutable()
            restore(self.job); self.assertEqual(read_json(target),original)
            install(self.job,target); mark_finished(self.job)
            self.assertEqual(self.job.data['state'],'FINISHED_UNRENDERED')
    def test_restore_does_not_destroy_manual_edits(self):
        self.draft(); target=self.root/'target'/'draft_content.json'; d=fixture(target); d['tracks']=[]; atomic_json(target,d)
        with patch('videopilot.capcut.capcut_running',return_value=False):
            install(self.job,target); changed=read_json(target); changed['name']='Manual edit'; atomic_json(target,changed)
            with self.assertRaises(UserError): restore(self.job)
    def test_capcut_running_blocks_install(self):
        self.draft()
        with patch('videopilot.capcut.capcut_running',return_value=True),self.assertRaises(UserError): install(self.job,self.root/'anything')
    def fake_voice(self,job,plan,speed,cancel,log):
        files=[job.folder/'audio'/f'{i:03d}.wav' for i in (1,2)]
        for p in files: wav(p,7.5)
        return files,[7.5,7.5]
    def test_manual_resume_to_complete_draft_no_render(self):
        template=self.root/'template'/'draft_content.json'; fixture(template); self.job.settings.template_path=str(template)
        atomic_json(self.job.folder/'script.json',PLAN)
        with patch('videopilot.pipeline.synthesize',side_effect=self.fake_voice):
            pipeline.run(self.job,self.cancel,lambda _:None)
            self.assertEqual(self.job.data['state'],'WAITING_FOR_IMAGES')
            timeline=read_json(self.job.folder/'timeline.json'); incoming=self.root/'incoming'; incoming.mkdir()
            from PIL import Image
            for shot in timeline['shots']: Image.new('RGB',(32,32),'blue').save(incoming/f'{shot["id"]}.png')
            self.assertEqual(pipeline.import_images(self.job,incoming),4)
            pipeline.run(self.job,self.cancel,lambda _:None)
        self.assertEqual(self.job.data['state'],'READY_FOR_CAPCUT')
        self.assertFalse(read_json(self.job.folder/'validation.json')['rendered'])
        self.assertFalse(any(self.job.folder.rglob('*.mp4')))
        self.assertFalse((self.job.folder/'run.lock').exists())
    def test_modified_image_invalidates_cache(self):
        atomic_json(self.job.folder/'script.json',PLAN)
        with patch('videopilot.pipeline.synthesize',side_effect=self.fake_voice): pipeline.run(self.job,self.cancel,lambda _:None)
        incoming=self.root/'incoming'; incoming.mkdir(); from PIL import Image
        Image.new('RGB',(30,30),'blue').save(incoming/'001_01.png'); pipeline.import_images(self.job,incoming)
        shot=read_json(self.job.folder/'timeline.json')['shots'][0]
        self.assertTrue(pipeline.cached_image(self.job,shot))
        (self.job.folder/'images'/'001_01.png').write_bytes(b'corrupted')
        self.assertFalse(pipeline.cached_image(self.job,shot))
    def test_network_images_require_explicit_billing_choice(self):
        self.job.settings.image_mode='gemini'; self.job.settings.paid_images=False; atomic_json(self.job.folder/'script.json',PLAN)
        with patch('videopilot.pipeline.synthesize',side_effect=self.fake_voice),patch('videopilot.pipeline.gemini_image') as image:
            with self.assertRaises(UserError): pipeline.run(self.job,self.cancel,lambda _:None,key='not-a-real-key')
            image.assert_not_called()
    def test_duration_failure_does_not_generate_images(self):
        atomic_json(self.job.folder/'script.json',PLAN)
        def voice(job,plan,speed,cancel,log): return [],[4.,4.]
        with patch('videopilot.pipeline.synthesize',side_effect=voice),patch('videopilot.pipeline.gemini_image') as image:
            pipeline.run(self.job,self.cancel,lambda _:None)
            self.assertEqual(self.job.data['state'],'NEEDS_DURATION_EDIT'); image.assert_not_called()
    def test_generated_script_gets_one_automatic_timing_revision(self):
        atomic_json(self.job.folder/'script.json',PLAN); self.job.data['script_origin']='codex'
        calls=[]
        def voice(job,plan,speed,cancel,log):
            calls.append(speed)
            if job.data.get('auto_fit_attempts',0)==0: return [],[4.,4.]
            return self.fake_voice(job,plan,speed,cancel,log)
        with patch('videopilot.pipeline.synthesize',side_effect=voice),patch('videopilot.pipeline.plan_video',return_value=PLAN) as planner:
            pipeline.run(self.job,self.cancel,lambda _:None)
            self.assertEqual(self.job.data['state'],'SCRIPT_READY')
            self.assertTrue(self.job.data['script_review_pending'])
            self.assertEqual(len(calls),1)
            pipeline.run(self.job,self.cancel,lambda _:None,approve_script=True)
            self.assertEqual(self.job.data['state'],'WAITING_FOR_IMAGES')
            self.assertEqual(planner.call_count,1)
            self.assertTrue((self.job.folder/'script-before-auto-fit.json').exists())

    def test_new_script_waits_for_explicit_review_before_voice(self):
        with patch('videopilot.pipeline.plan_video',return_value=PLAN) as planner,patch('videopilot.pipeline.synthesize',side_effect=self.fake_voice) as voice:
            # Create video also invokes Continue internally; new scripts must
            # still pause rather than consuming that initial call as approval.
            pipeline.run(self.job,self.cancel,lambda _:None,approve_script=True)
            self.assertEqual(self.job.data['state'],'SCRIPT_READY');voice.assert_not_called()
            self.assertTrue(self.job.data['script_review_pending'])
            self.assertTrue((self.job.folder/'script.txt').is_file())
            self.assertFalse((self.job.folder/'run.lock').exists())
            reopened=Job(self.job.folder)
            pipeline.run(reopened,self.cancel,lambda _:None)
            voice.assert_not_called()
            pipeline.run(reopened,self.cancel,lambda _:None,approve_script=True)
            self.assertEqual(reopened.data['state'],'WAITING_FOR_IMAGES')
            self.assertFalse(reopened.data['script_review_pending'])
            self.assertEqual(voice.call_count,1);self.assertEqual(planner.call_count,1)
    def test_cancel_does_not_claim_complete(self):
        self.cancel.set(); atomic_json(self.job.folder/'script.json',PLAN)
        pipeline.run(self.job,self.cancel,lambda _:None)
        self.assertEqual(self.job.data['state'],'STOPPED'); self.assertFalse((self.job.folder/'run.lock').exists())
    def test_secrets_not_serialized(self):
        serialized=(self.job.folder/'job.json').read_text()
        self.assertNotIn('api_key',serialized.lower()); self.assertNotIn('password',serialized.lower())

if __name__=='__main__': unittest.main()
