import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from videopilot.audio import compact_silence
from videopilot.core import Settings,Job,UserError,atomic_json,make_timeline,read_json
from videopilot.capcut import Template
from videopilot.image_cleanup import clean_visible_star,_star,detect_star
from videopilot.storage import clean_duplicates
from videopilot.revisions import create_revision
from videopilot.sound_library import select_sound
from test_system import PLAN,fixture,wav


class EditingTests(unittest.TestCase):
    def test_trim_preserves_speech_samples_and_short_pauses(self):
        speech=np.sin(np.arange(1000)*.2).astype(np.float32)*.2
        data=np.concatenate([speech,np.zeros(600),speech,np.zeros(100),speech,np.zeros(400)])
        result=compact_silence(data,1000)
        self.assertLess(len(result),len(data)-600)
        np.testing.assert_array_equal(result[np.abs(result)>.0032],data[np.abs(data)>.0032])
        self.assertTrue(np.any(np.convolve((result==0).astype(int),np.ones(100),mode='valid')==100))
        with self.assertRaises(UserError):compact_silence(np.zeros(200),1000)

    def test_user_eight_second_setting_and_cuts_match_beats(self):
        timeline=make_timeline(PLAN,[3.25,11.2],Settings(shot_seconds=8))
        self.assertEqual(timeline['shots'][1]['start'],3250000)
        self.assertLessEqual(max(s['duration'] for s in timeline['shots']),8000000)
        self.assertGreater(max(s['duration'] for s in timeline['shots']),5000000)
        self.assertEqual(sum(s['duration'] for s in timeline['shots']),timeline['duration'])

    def test_native_motion_and_effect_at_time_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sample=root/'sample'/'draft_content.json';fixture(sample)
            settings=Settings(idea='test',bgm='none');plan=copy.deepcopy(PLAN);plan['scenes'][0]['sfx']=True
            timeline=make_timeline(plan,[3.,4.],settings)
            (root/'images').mkdir()
            for shot in timeline['shots']:Image.new('RGB',(16,16)).save(root/'images'/f'{shot["id"]}.png')
            wav(root/'audio/narration.wav',7);wav(root/'audio/whoosh.wav',.28)
            draft=Template(sample).build(timeline,root,settings)
            video=next(t for t in draft['tracks'] if t['type']=='video')
            for seg in video['segments']:
                keys=seg['common_keyframes'][0]
                self.assertEqual(keys['property_type'],'KFTypeScale')
                first,last=keys['keyframe_list'][0],keys['keyframe_list'][-1]
                self.assertTrue(all(a['time_offset']<b['time_offset'] for a,b in zip(keys['keyframe_list'],keys['keyframe_list'][1:])))
                self.assertNotEqual(first['values'],last['values'])
                self.assertEqual(first['time_offset'],0)
                self.assertLess(last['time_offset'],seg['target_timerange']['duration'])
            effects=[s for t in draft['tracks'] if t['type']=='audio' for s in t['segments'] if s['volume']==.45]
            self.assertEqual(effects[0]['target_timerange']['start'],0)

    def test_corner_cleanup_preserves_unmarked_image_and_is_not_repeated(self):
        base=Image.new('RGB',(768,1024),(55,35,20))
        unchanged,info=clean_visible_star(base)
        self.assertEqual(base.tobytes(),unchanged.tobytes())
        for x in (72,648):
            pixels=np.array(base);mask=_star(48)>0
            pixels[900:948,x:x+48][mask]=170
            marked=Image.fromarray(pixels)
            self.assertIsNotNone(detect_star(marked))
            cleaned,info=clean_visible_star(marked)
            self.assertEqual(info['status'],'cleaned')
            self.assertIsNone(detect_star(cleaned))
            np.testing.assert_array_equal(np.array(cleaned)[:850],pixels[:850])

    def test_cleanup_only_deletes_verified_internal_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='test'),tmp)
            root=job.folder/'browser-downloads/VideoPilot/q';root.mkdir(parents=True)
            kept=job.folder/'flow_variants/001_01';kept.mkdir(parents=True)
            source=root/'001_01__v1.png';source.write_bytes(b'original');(kept/'v1.png').write_bytes(b'original')
            atomic_json(job.folder/'FLOW_QUEUE.json',{'queue_id':'q'})
            receipt={'complete':True,'shot_id':'001_01','queue_id':'q','variants':[{'filename':source.name}]}
            atomic_json(root/'001_01.receipt.json',receipt)
            (job.folder/'run.lock').write_text('busy')
            with self.assertRaises(UserError):clean_duplicates(job)
            (job.folder/'run.lock').unlink()
            self.assertEqual(clean_duplicates(job),8)
            self.assertTrue((kept/'v1.png').exists())
            self.assertTrue(source.samefile(kept/'v1.png'))
            replacement=source.with_suffix('.tmp');replacement.write_bytes(b'different');replacement.replace(source)
            self.assertEqual((kept/'v1.png').read_bytes(),b'original')
            self.assertEqual(clean_duplicates(job),0)
            self.assertTrue(source.exists())

    def test_revision_preserves_installed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Job.create(Settings(idea='test'),tmp);source.data['installed_path']='original.json';source.save()
            atomic_json(source.folder/'script.json',PLAN);before=source.path.read_bytes()
            with patch('videopilot.revisions.plan_video',return_value=PLAN):
                revised=create_revision(source,threading.Event(),lambda _:None,tmp)
            self.assertEqual(before,source.path.read_bytes());self.assertNotIn('installed_path',revised.data)
            self.assertEqual(revised.data['revision_of'],str(source.folder))

    def test_library_match_uses_visual_not_generic_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);effects=root/'audio/effects';effects.mkdir(parents=True)
            wav(effects/'a.wav',.2);wav(effects/'b.wav',.2)
            atomic_json(effects/'index.json',[{'name':'door creak','file':'a.wav'},{'name':'ocean','file':'b.wav'}])
            self.assertEqual(select_sound(root,{'prompt':'ocean style','sound_context':'opens door'}),effects/'a.wav')
            self.assertIsNone(select_sound(root,{'prompt':'flour falling'}))


if __name__=='__main__':unittest.main()
