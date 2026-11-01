import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from videopilot.core import Job,Settings,UserError,Cancelled,atomic_json,read_json,file_hash
from videopilot import draft_cleanup as D
from videopilot.image_cleanup import _star,detect_star


class DraftCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.job=Job.create(Settings(idea='Draft repair'),self.tmp.name)
        self.cancel=threading.Event();self.logs=[]
        self.images=self.job.folder/'images';self.images.mkdir()
        self.marked=self.images/'001_01.png';self.clean=self.images/'001_02.png'
        base=Image.new('RGB',(768,1024),(55,35,20));pixels=np.array(base)
        pixels[900:948,72:120][_star(48)>0]=170
        Image.fromarray(pixels).save(self.marked);base.save(self.clean)
        for image in (self.marked,self.clean):
            atomic_json(image.with_suffix('.json'),{'sha256':file_hash(image),'signature':'unchanged','visible_star_cleanup':{'status':'cleaned','version':3}})
        self.draft=self.job.folder/'installed'/'draft_content.json'
        self.write_draft([self.marked,self.clean,self.marked])
        self.job.data['installed_path']=str(self.draft);self.job.data['installed_hash']=file_hash(self.draft);self.job.save()
        process=patch.object(D.capcut,'capcut_running',return_value=False)
        process.start();self.addCleanup(process.stop)

    def write_draft(self,paths):
        atomic_json(self.draft,{'materials':{'videos':[{'id':str(i),'path':str(p)} for i,p in enumerate(paths)]},
            'tracks':[{'segments':[{'material_id':str(i),'target_timerange':{'start':i*3000000,'duration':3000000},'custom_edit':True} for i in range(len(paths))]}]})

    def repair(self):return D.remove_draft_stars(self.job,self.cancel,self.logs.append)

    def test_installed_repair_skips_clean_images_preserves_draft_and_reuses_cache(self):
        draft=self.draft.read_bytes();state=self.job.path.read_bytes()
        marked=self.marked.read_bytes();clean=self.clean.read_bytes();clean_meta=self.clean.with_suffix('.json').read_bytes()
        with patch.object(D,'clean_visible_star',wraps=D.clean_visible_star) as cleaner:
            self.assertEqual(self.repair(),1);self.assertEqual(cleaner.call_count,2)
        self.assertIsNone(detect_star(Image.open(self.marked)))
        self.assertEqual(self.clean.read_bytes(),clean);self.assertEqual(self.clean.with_suffix('.json').read_bytes(),clean_meta)
        self.assertEqual(self.draft.read_bytes(),draft);self.assertEqual(self.job.path.read_bytes(),state)
        self.assertEqual(read_json(self.marked.with_suffix('.json'))['sha256'],file_hash(self.marked))
        self.assertEqual(read_json(self.marked.with_suffix('.json'))['signature'],'unchanged')
        backups=list((self.job.folder/'backups').glob('star-repair-*/manifest.json'));self.assertEqual(len(backups),1)
        entry=next(e for e in read_json(backups[0]) if e['path']==str(self.marked))
        self.assertEqual(Path(entry['backup']).read_bytes(),marked)
        with patch.object(D,'clean_visible_star',side_effect=AssertionError('Already checked')):
            self.assertEqual(self.repair(),0)
        self.assertFalse((self.job.folder/'run.lock').exists())

    def test_busy_editor_and_cancel_do_not_modify_images(self):
        original=self.marked.read_bytes()
        with patch.object(D.capcut,'capcut_running',return_value=True):
            with self.assertRaisesRegex(UserError,'Close CapCut'):self.repair()
        self.cancel.set()
        with self.assertRaises(Cancelled):self.repair()
        self.assertEqual(self.marked.read_bytes(),original)
        self.assertFalse((self.job.folder/'run.lock').exists())

    def test_unused_materials_are_not_repaired(self):
        content=read_json(self.draft);content['materials']['videos'].append({'id':'unused','path':str(self.job.folder/'missing.png')})
        atomic_json(self.draft,content)
        self.assertEqual(self.repair(),1)

    def test_render_failure_leaves_original_media_and_metadata_intact(self):
        clip=self.job.folder/'graphics'/'001_01.mp4';clip.parent.mkdir();clip.write_bytes(b'original clip')
        self.write_draft([clip,self.clean])
        atomic_json(self.job.folder/'graphics_report.json',{'clips':{'001_01':{'path':str(clip)}}})
        original=self.marked.read_bytes();metadata=self.marked.with_suffix('.json').read_bytes()
        with patch.object(D,'_render_affected',side_effect=RuntimeError('Renderer failed')):
            with self.assertRaisesRegex(RuntimeError,'Renderer failed'):self.repair()
        self.assertEqual(self.marked.read_bytes(),original);self.assertEqual(self.marked.with_suffix('.json').read_bytes(),metadata)
        self.assertEqual(clip.read_bytes(),b'original clip')

    def test_failed_commit_restores_image_and_metadata(self):
        image=self.marked.read_bytes();meta=self.marked.with_suffix('.json').read_bytes()
        replace=D.os.replace
        def fail_metadata(source,destination):
            if Path(destination)==self.marked.with_suffix('.json') and '.star-repair-' in str(source):
                raise OSError('Cannot replace metadata')
            return replace(source,destination)
        with patch.object(D.os,'replace',side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError,'Cannot replace metadata'):self.repair()
        self.assertEqual(self.marked.read_bytes(),image);self.assertEqual(self.marked.with_suffix('.json').read_bytes(),meta)
        self.assertFalse((self.job.folder/'run.lock').exists())

    def test_only_affected_graphics_are_rebuilt_with_saved_plans(self):
        clips={};paths=[]
        for sid,image in [('001_01',self.marked),('001_02',self.clean)]:
            path=self.job.folder/'graphics'/f'{sid}.mp4';path.parent.mkdir(exist_ok=True);path.write_bytes(b'original '+sid.encode());paths.append(path)
            atomic_json(path.with_suffix('.json'),{'signature':'old','sha256':file_hash(path)})
            clips[sid]={'path':str(path),'source_shot_id':sid,'source_image_sha256':file_hash(image),'duration':3000000}
        self.write_draft(paths);draft=self.draft.read_bytes()
        atomic_json(self.job.folder/'graphics_report.json',{'clips':clips})
        shot={'id':'001_01','scene':1,'start':0,'duration':3000000}
        atomic_json(self.job.folder/'edit_timeline.json',{'shots':[shot],'duration':3000000})
        atomic_json(self.job.folder/'script.json',{'scenes':[]})
        overlay={'elements':[{'kind':'arrow','points':[[.1,.2],[.4,.5]],'color':'#ffffff','label':'','start':0,'end':2}]}
        atomic_json(self.job.folder/'overlay-plans'/'001_01.json',{'plan':overlay})
        def render(staging,plan,timeline,cancel,log,**kwargs):
            self.assertEqual(kwargs['selected_shots'],[shot]);self.assertEqual(kwargs['planned_overlays'],{'001_01':overlay})
            self.assertFalse(staging.data.get('installed_path'))
            self.assertNotEqual(file_hash(staging.folder/'images'/'001_01.png'),file_hash(self.marked))
            path=staging.folder/'repaired.mp4';path.write_bytes(b'repaired clip')
            atomic_json(path.with_suffix('.json'),{'signature':'new','sha256':file_hash(path)})
            return {'clips':{'001_01':{'path':str(path)}}}
        with patch('videopilot.remotion_graphics.render_graphics',side_effect=render) as renderer,patch('videopilot.overlay_planner.plan_overlay',side_effect=AssertionError('No new planning')):
            self.assertEqual(self.repair(),1);renderer.assert_called_once()
        self.assertEqual(paths[0].read_bytes(),b'repaired clip');self.assertEqual(paths[1].read_bytes(),b'original 001_02')
        self.assertEqual(self.draft.read_bytes(),draft)
        updated=read_json(self.job.folder/'graphics_report.json')
        self.assertEqual(updated['clips']['001_01']['source_image_sha256'],file_hash(self.marked))
        self.assertEqual(updated['clips']['001_02'],clips['001_02'])
