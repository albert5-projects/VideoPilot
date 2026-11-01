import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from videopilot.core import Job,Settings,UserError,Cancelled,atomic_json,read_json,make_timeline,validate_plan,file_hash
from videopilot.capcut import Template
from videopilot.pipeline import preparation_signature
from videopilot.remotion_graphics import select_shots,graphic_for,render_graphics
from videopilot.storage import clean_unused_graphics
from test_system import PLAN,fixture,wav


class CustomizationTests(unittest.TestCase):
    def test_custom_style_and_controls_validate(self):
        settings=Settings(idea='test',style='Hand-drawn ink on rice paper, muted orange accents',image_motion=False,graphics_percent=40)
        settings.validate()
        timeline=make_timeline(PLAN,[3,3],settings)
        self.assertIn(settings.style,timeline['shots'][0]['prompt'])
        for key,value in [('graphics_percent',101),('graphics_percent',-1),('graphics_percent',float('nan')),('image_motion','false'),('graphics_theme','unknown'),('graphics_accent','red'),('style','')]:
            bad=copy.copy(settings);setattr(bad,key,value)
            with self.assertRaises(UserError):bad.validate()

    def test_graphics_percentage_rounds_runtime_without_changing_timing(self):
        timeline=make_timeline(PLAN,[12,18],Settings(shot_seconds=3))
        original=copy.deepcopy(timeline)
        self.assertEqual(select_shots(timeline,0),[])
        self.assertEqual(select_shots(timeline,100),timeline['shots'])
        chosen=select_shots(timeline,40)
        self.assertEqual(sum(s['duration'] for s in chosen),12000000)
        self.assertEqual(len({s['id'] for s in chosen}),len(chosen))
        self.assertEqual(timeline,original)

    def test_graphics_and_motion_settings_do_not_invalidate_narration(self):
        s=Settings(idea='test');before=preparation_signature(PLAN,s)
        s.image_motion=False;s.remotion_enabled=True;s.graphics_percent=70;s.graphics_theme='Bold'
        self.assertEqual(before,preparation_signature(PLAN,s))
        s.shot_seconds=2
        self.assertNotEqual(before,preparation_signature(PLAN,s))

    def test_disabled_remotion_never_requires_node_or_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='test'),tmp)
            with patch('videopilot.remotion_graphics.runtime',side_effect=AssertionError('must not run')):
                report=render_graphics(job,PLAN,make_timeline(PLAN,[3,3],job.settings),threading.Event(),lambda _:None)
            self.assertEqual(report['clips'],{})

    def test_graphics_content_validation_and_legacy_fallback(self):
        self.assertEqual(graphic_for(PLAN,{'scene':1})['title'],PLAN['scenes'][0]['overlay'])
        p=copy.deepcopy(PLAN);p['scenes'][0]['graphic']={'kind':'comparison','title':'A comparison','items':['Only one']}
        with self.assertRaises(UserError):validate_plan(p)
        p['scenes'][0]['graphic']['items']=['Before','After'];validate_plan(p)

    def test_static_images_and_rendered_clips_have_no_extra_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sample=root/'sample/draft_content.json';fixture(sample)
            settings=Settings(idea='test',image_motion=False,sfx=False,bgm='none')
            timeline=make_timeline(PLAN,[3,3],settings);(root/'images').mkdir()
            for shot in timeline['shots']:Image.new('RGB',(8,8)).save(root/'images'/f'{shot["id"]}.png')
            wav(root/'audio/narration.wav',6)
            draft=Template(sample).build(timeline,root,settings)
            segments=next(t for t in draft['tracks'] if t['type']=='video')['segments']
            self.assertTrue(all(not s['common_keyframes'] and s['clip']['scale']=={'x':1.,'y':1.} for s in segments))
            captions=next(t for t in draft['tracks'] if t.get('name')=='Captions') if any(t.get('name')=='Captions' for t in draft['tracks']) else next(t for t in draft['tracks'] if t['type']=='text')
            self.assertTrue(all(s['clip']['transform']['y']==-.76 for s in captions['segments']))
            # Renderer validation happens before the adapter. Here check native mapping only.
            video=root/'render.mp4';video.write_bytes(b'adapter fixture')
            timeline['rendered_clips']={timeline['shots'][0]['id']:{'path':str(video),'duration':3000000}}
            settings.image_motion=True;draft=Template(sample).build(timeline,root,settings)
            segments=next(t for t in draft['tracks'] if t['type']=='video')['segments']
            self.assertFalse(segments[0]['common_keyframes']);self.assertTrue(segments[1]['common_keyframes'])
            material=next(m for m in draft['materials']['videos'] if m['id']==segments[0]['material_id'])
            self.assertEqual(material['type'],'video');self.assertFalse(material['has_audio'])
            self.assertEqual(segments[0]['volume'],0)
            sid=timeline['shots'][0]['id'];rendered=timeline['rendered_clips'][sid]
            rendered.update(source_shot_id=sid,source_image_sha256=file_hash(root/'images'/f'{sid}.png'))
            Template(sample).build(timeline,root,settings)
            Image.new('RGB',(8,8),'red').save(root/'images'/f'{sid}.png')
            with self.assertRaisesRegex(UserError,'outdated or different image'):Template(sample).build(timeline,root,settings)
            captions=next(t for t in draft['tracks'] if t['type']=='text')
            self.assertTrue(all(s['clip']['transform']=={'x':0.,'y':-.76} for s in captions['segments']))

    def test_pruning_keeps_referenced_and_installed_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='test'),tmp);root=job.folder/'graphics';root.mkdir()
            used=root/('001_01-'+'a'*16+'.mp4');old=root/('002_01-'+'b'*16+'.mp4')
            for path in (used,old):path.write_bytes(b'clip');atomic_json(path.with_suffix('.json'),{'sha256':file_hash(path)})
            atomic_json(job.folder/'capcut/draft_content.json',{'materials':{'videos':[{'path':str(used)}]}})
            job.data['state']='READY_FOR_CAPCUT';job.data['installed_path']='installed.json'
            self.assertEqual(clean_unused_graphics(job),0);self.assertTrue(old.exists())
            job.data.pop('installed_path');self.assertGreater(clean_unused_graphics(job),0)
            self.assertTrue(used.exists());self.assertFalse(old.exists())

    def test_planner_gets_freeform_style_and_graphics_brief(self):
        from videopilot.providers import plan_video
        with patch('videopilot.providers.run_codex',return_value=PLAN) as run:
            plan_video(Settings(idea='test',style='Clay models in blue light',remotion_enabled=True),Path('.'),threading.Event())
        prompt=run.call_args.args[0]
        self.assertIn('Clay models in blue light',prompt);self.assertIn('graphics_percent',prompt)

    def test_cancel_keeps_completed_render_but_removes_partial_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='test',remotion_enabled=True,graphics_percent=100),tmp)
            timeline=make_timeline(PLAN,[3,3],job.settings);(job.folder/'images').mkdir()
            for shot in timeline['shots']:Image.new('RGB',(8,8)).save(job.folder/'images'/f'{shot["id"]}.png')
            cancel=threading.Event()
            class Worker:
                def __init__(self,args,**kwargs):
                    request=read_json(args[-1]);item=request['items'][0]
                    Path(item['output']).with_suffix('.ready.mp4').write_bytes(b'completed')
                    (Path(request['work'])/'unfinished.partial.mp4').write_bytes(b'incomplete')
                    self.done=False;self.returncode=0;cancel.set()
                def poll(self):return 0 if self.done else None
                def wait(self,*args,**kwargs):self.done=True;return 0
            env={'root':tmp,'node':'node','browser':'browser','version':'4.0.448'}
            with patch('videopilot.overlay_planner.plan_overlay',return_value={'elements':[{'kind':'arrow'}]}),patch('videopilot.remotion_graphics.runtime',return_value=env),patch('videopilot.remotion_graphics.shutil.which',return_value='ffprobe'),patch('videopilot.remotion_graphics.subprocess.Popen',Worker),patch('videopilot.remotion_graphics.probe_video',return_value=3000000):
                with self.assertRaises(Cancelled):render_graphics(job,PLAN,timeline,cancel,lambda _:None)
            clips=list((job.folder/'graphics').glob('*.mp4'))
            self.assertEqual(len(clips),1);self.assertEqual(clips[0].read_bytes(),b'completed')
            self.assertTrue(clips[0].with_suffix('.json').exists())
            self.assertFalse(list((job.folder/'graphics').glob('remotion-*')))


if __name__=='__main__':unittest.main()
