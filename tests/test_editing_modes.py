import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from videopilot.core import Settings,Job,UserError,make_timeline,read_json
from videopilot.editing import gentle_camera,validate_edit,prepare_edit
from videopilot import kdenlive
from test_system import PLAN,wav

def decisions(timeline):
    return {'rationale':'A clear edit','music_gain':.09,'caption_color':'#FFFFFF','emphasis_color':'#FFD166','shots':[
        {'id':s['id'],'reason':'Keep subject readable','camera':[{'at':0,'scale':1.,'x':0.,'y':0.,'rotation':0.},{'at':1,'scale':1.08,'x':.01,'y':0.,'rotation':0.}],
         'graphic':{'kind':'none','title':'','items':[],'icons':[]},'cue_seconds':[0.],'emphasis':'Look closely','sfx_file':'','sfx_offset':0.,'sfx_gain':.3,'transition':'fade'} for s in timeline['shots']]}

class EditingModesTests(unittest.TestCase):
    def test_gentle_motion_and_static_limits(self):
        for style in ('slow_zoom','pan','float','mixed'):
            keys=gentle_camera({},Settings(motion_style=style))
            self.assertLessEqual(max(k['scale'] for k in keys),1.07)
            self.assertTrue(all(k['rotation']==0 and abs(k['x'])<=.015 and abs(k['y'])<=.006 for k in keys))
        self.assertTrue(all(k['scale']==1 for k in gentle_camera({},Settings(image_motion=False))))

    def test_editor_rejects_missing_shots_unsafe_paths_and_invalid_keys(self):
        timeline=make_timeline(PLAN,[3,3],Settings());good=decisions(timeline)
        validate_edit(good,timeline,PLAN,{})
        for mutate in (lambda d:d['shots'].pop(),lambda d:d['shots'][0].update(sfx_file='../../file.wav'),lambda d:d['shots'][0]['camera'][1].update(scale=9),lambda d:d['shots'][0]['camera'][1].update(at=.2)):
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(UserError):validate_edit(bad,timeline,PLAN,{})

    def test_codex_receives_actual_images_and_cached_edit_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='Editor',editing_mode='codex',image_motion=False),tmp)
            timeline=make_timeline(PLAN,[3,3],job.settings);(job.folder/'images').mkdir()
            for s in timeline['shots']:Image.new('RGB',(100,100),'blue').save(job.folder/'images'/f'{s["id"]}.png')
            with patch('videopilot.providers.run_codex',return_value=decisions(timeline)) as codex:
                edit=prepare_edit(job,PLAN,timeline,threading.Event(),lambda _:None)
                self.assertTrue(codex.call_args.kwargs['images'][0].is_file())
                self.assertEqual(edit['shots'][0]['camera'][-1]['scale'],1.08)
                self.assertEqual(edit['edit_style']['music_gain'],.09)
                prepare_edit(job,PLAN,timeline,threading.Event(),lambda _:None);self.assertEqual(codex.call_count,1)
            self.assertNotIn('camera',timeline['shots'][0])

    def test_rule_mode_never_calls_codex_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='Rules'),tmp);timeline=make_timeline(PLAN,[3,3],job.settings)
            with patch('videopilot.editing.direct_edit',side_effect=AssertionError('not needed')):
                edited=prepare_edit(job,PLAN,timeline,threading.Event(),lambda _:None)
            self.assertEqual(edited['editing_mode'],'rules')

    def test_kdenlive_contains_tracks_subtitles_and_camera_keys_without_capcut_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='Kdenlive',video_editor='kdenlive',sfx=False,bgm='none'),tmp)
            timeline=make_timeline(PLAN,[3,3],job.settings);(job.folder/'images').mkdir()
            for s in timeline['shots']:Image.new('RGB',(100,100),'red').save(job.folder/'images'/f'{s["id"]}.png')
            wav(job.folder/'audio/narration.wav',6)
            timeline=prepare_edit(job,PLAN,timeline,threading.Event(),lambda _:None)
            result=kdenlive.build(job,timeline);root=kdenlive.validate(result)
            self.assertTrue(result.with_suffix('.kdenlive.ass').is_file())
            self.assertTrue(root.findall(".//property[@name='transition.rect']"))
            self.assertEqual(root.find("playlist[@id='main_bin']/property[@name='kdenlive:docproperties.version']").text,'1.1')
            self.assertEqual(root.find("tractor[@id='project']").get('out'),'179')

if __name__=='__main__':unittest.main()
