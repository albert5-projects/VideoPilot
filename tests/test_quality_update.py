import copy,csv,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from PIL import Image,ImageDraw
from videopilot.core import Job,Settings,atomic_json,read_json,file_hash,make_timeline,validate_plan
from videopilot.audio import duration_tolerance,wav_info
from videopilot.image_cleanup import CLEANUP_VERSION,detect_star,clean_visible_star,upgrade_project_images,erase_region
from videopilot.sound_catalog import discover,write_catalog
from videopilot.sound_library import import_library,select_sound
from videopilot import pipeline
from videopilot.capcut import Template
from videopilot.remotion_graphics import graphic_for
from test_system import PLAN,fixture,wav


class QualityUpdateTests(unittest.TestCase):
    def test_small_duration_drift_does_not_trigger_speed_changes_or_rewrite(self):
        for actual in (18.,18.01,27.,33.,90.):
            with self.subTest(actual=actual),tempfile.TemporaryDirectory() as tmp:
                job=Job.create(Settings(idea='test',duration=30,image_mode='manual',bgm='none',sfx=False),tmp)
                atomic_json(job.folder/'script.json',PLAN);job.data['script_origin']='codex'
                def voice(*args):
                    paths=[job.folder/'audio'/f'{i}.wav' for i in (1,2)]
                    for path in paths:wav(path,actual/2)
                    return paths,[actual/2,actual/2]
                with patch('videopilot.pipeline.synthesize',side_effect=voice) as synth,patch('videopilot.pipeline.plan_video') as rewrite:
                    pipeline.run(job,threading.Event(),lambda _:None)
                self.assertEqual(synth.call_count,1);rewrite.assert_not_called()
                self.assertEqual(job.data['state'],'WAITING_FOR_IMAGES');self.assertEqual(job.data['effective_speed'],1.)
        self.assertEqual(duration_tolerance(60),6);self.assertEqual(duration_tolerance(1800),15)

    def cache_fixture(self,root):
        folder=root/'CapCut/User Data/Cache/music';folder.mkdir(parents=True)
        known=folder/('a'*32+'.mp3');unknown=folder/('b'*32+'.mp3')
        known.write_bytes(b'fake mp3');unknown.write_bytes(b'fake mp3')
        atomic_json(folder.parent.parent/'Projects/com.lveditor.draft/sample/draft_content.json',
            {'materials':{'audios':[{'path':str(known),'name':'Door creak','type':'sound'}]}})
        return folder,known,unknown

    def test_recovers_cache_names_without_renaming_or_guessing_unknowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,known,unknown=self.cache_fixture(root)
            entries=discover(folder)
            self.assertEqual(entries[0]['name'],'Door creak');self.assertEqual(entries[1]['name'],'')
            self.assertTrue(known.exists());self.assertTrue(unknown.exists())
            report=root/'report.csv';write_catalog(entries,report)
            with report.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
            self.assertEqual(rows[1][0],'Door creak');self.assertEqual(rows[2][0],'(unidentified)')

    def test_effect_import_is_lazy_and_only_decodes_used_effect_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_,_=self.cache_fixture(root);job=Job.create(Settings(idea='test'),root/'jobs')
            with patch('videopilot.sound_library.subprocess.run',side_effect=AssertionError('Import should not decode')):
                import_library(job,folder,threading.Event(),lambda _:None)
            self.assertFalse(list((job.folder/'audio/effects').glob('*.wav')))
            def decode(args,**kwargs):wav(Path(args[-1]),.5);return SimpleNamespace(returncode=0)
            with patch('videopilot.sound_library.shutil.which',return_value='ffmpeg'),patch('videopilot.sound_library.subprocess.run',side_effect=decode) as run:
                selected=select_sound(job.folder,{'sound_context':'door opening creak'})
                self.assertTrue(selected.is_file());self.assertEqual(run.call_count,1)
                self.assertEqual(select_sound(job.folder,{'sound_context':'door creak'}),selected)
                self.assertEqual(run.call_count,1)

    def test_id3_title_is_used_when_a_cache_hash_has_embedded_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);payload=b'\x03Soft rain\0';frame=b'TIT2'+len(payload).to_bytes(4,'big')+b'\0\0'+payload
            (root/('c'*32+'.mp3')).write_bytes(b'ID3\x03\0\0\0\0\0'+bytes([len(frame)])+frame)
            entry=discover(root)[0];self.assertEqual(entry['name'],'Soft rain');self.assertEqual(entry['name_source'],'ID3 title')

    def test_mp3_background_is_referenced_directly_even_if_old_wav_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sample=root/'sample/draft_content.json';fixture(sample)
            mp3=root/'chosen.mp3';mp3.write_bytes(b'compressed audio fixture')
            settings=Settings(idea='test',bgm='file',bgm_path=str(mp3),sfx=False);settings.validate()
            timeline=make_timeline(PLAN,[3,3],settings);(root/'images').mkdir()
            for s in timeline['shots']:Image.new('RGB',(8,8)).save(root/'images'/f'{s["id"]}.png')
            wav(root/'audio/narration.wav',6);wav(root/'audio/music.wav',6)
            (root/'audio/music.mp3').write_bytes(mp3.read_bytes())
            with patch('videopilot.capcut.audio_info',side_effect=lambda p:{'duration':2.} if Path(p).suffix=='.mp3' else wav_info(p)):
                draft=Template(sample).build(timeline,root,settings)
            music=[m for m in draft['materials']['audios'] if m.get('path','').endswith('/music.mp3')]
            self.assertEqual(len(music),3)
            self.assertFalse(any(m.get('path','').endswith('/music.wav') for m in draft['materials']['audios']))

    def test_cached_landscape_is_reprocessed_and_image_receipt_updated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='test',aspect='16:9'),tmp)
            timeline=make_timeline(PLAN,[3,3],job.settings);shot=timeline['shots'][0]
            path=job.folder/'images'/f'{shot["id"]}.png';path.parent.mkdir()
            image=Image.new('RGB',(1920,1080),(50,40,30));draw=ImageDraw.Draw(image)
            x,y,r=1780,946,34
            draw.polygon([(x,y-r),(x+12,y-12),(x+r,y),(x+12,y+12),(x,y+r),(x-12,y+12),(x-r,y),(x-12,y-12)],fill=(190,185,180))
            image.save(path);before=file_hash(path)
            atomic_json(path.with_suffix('.json'),{'signature':pipeline.image_signature(job,shot),'sha256':before,'source':'manual import'})
            self.assertEqual(upgrade_project_images(job,timeline,lambda _:None),1)
            self.assertNotEqual(file_hash(path),before);self.assertTrue(pipeline.cached_image(job,shot))
            self.assertEqual(read_json(path.with_suffix('.json'))['visible_star_cleanup']['version'],CLEANUP_VERSION)
            self.assertEqual(upgrade_project_images(job,timeline,lambda _:None),0)
            self.assertEqual(file_hash(job.folder/'images_before_cleanup'/path.name),before)

    def test_cleanup_leaves_unmarked_texture_untouched_and_manual_repair_is_local(self):
        noise=np.random.default_rng(10).integers(20,200,(768,1376,3),dtype=np.uint8);image=Image.fromarray(noise)
        self.assertIsNone(detect_star(image))
        result,report=clean_visible_star(image);self.assertEqual(result.tobytes(),image.tobytes())
        repaired=erase_region(image,(1250,650,1290,690))
        self.assertEqual(repaired.crop((0,0,1200,600)).tobytes(),image.crop((0,0,1200,600)).tobytes())

    def test_illustrated_plan_supports_semantic_icons_and_legacy_layouts(self):
        plan=copy.deepcopy(PLAN)
        plan['scenes'][0]['graphic']={'kind':'process','title':'Prepare bread','items':['Pour water','Bake loaf'],'icons':['water','bread']}
        validate_plan(plan);graphic=graphic_for(plan,{'scene':1})
        self.assertEqual(graphic['icons'],['water','bread'])
        plan['scenes'][0]['graphic']={'kind':'steps','title':'Prepare bread','items':['Pour water','Bake loaf']}
        graphic=graphic_for(plan,{'scene':1});self.assertEqual(graphic['kind'],'process');self.assertEqual(graphic['icons'][0],'water')


if __name__=='__main__':unittest.main()
