import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from videopilot.core import atomic_json,UserError
from videopilot.image_audit import audit_images,require_distinct_imports

class ImageAuditTests(unittest.TestCase):
    def test_duplicate_auto_import_is_detected_before_graphics(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=SimpleNamespace(folder=Path(tmp));images=job.folder/'images';images.mkdir()
            im=Image.new('RGB',(64,36));im.putdata([(x*3,y*6,(x+y)*2) for y in range(36) for x in range(64)])
            shots=[{'id':'002_01','prompt':'ingredients'},{'id':'003_01','prompt':'pepper'}]
            for shot in shots:
                im.save(images/(shot['id']+'.png'))
                atomic_json(images/(shot['id']+'.json'),{'source':'Google Flow browser helper'})
            report=audit_images(job,{'shots':shots})
            self.assertEqual(report['near_duplicate_automatic_imports'][0]['shots'],['002_01','003_01'])
            with self.assertRaisesRegex(UserError,'Nearly identical'):require_distinct_imports(job,{'shots':shots})
            atomic_json(images/'003_01.json',{'source':'Google Flow selected variant'})
            require_distinct_imports(job,{'shots':shots})

    def test_distinct_images_and_repeated_prompt_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=SimpleNamespace(folder=Path(tmp));images=job.folder/'images';images.mkdir()
            shots=[{'id':'001_01','prompt':'same'},{'id':'002_01','prompt':'same'}]
            for i,shot in enumerate(shots):
                im=Image.new('RGB',(64,36));im.putdata([(x*3,y*6,(x+y)*2) for y in range(36) for x in range(64)])
                im.save(images/(shot['id']+'.png'));atomic_json(images/(shot['id']+'.json'),{'source':'Google Flow browser helper'})
            require_distinct_imports(job,{'shots':shots})
            shots[1]['prompt']='different'
            Image.new('RGB',(64,36),'blue').save(images/'002_01.png')
            require_distinct_imports(job,{'shots':shots})

    def test_repair_copy_preserves_timing_and_does_not_share_image_files(self):
        import threading
        from videopilot.core import Job,Settings,read_json
        from videopilot.image_audit import create_image_repair_copy
        with tempfile.TemporaryDirectory() as tmp:
            source=Job.create(Settings(idea='Repair'),tmp)
            atomic_json(source.folder/'script.json',{'scenes':[]})
            timeline={'shots':[{'id':'001_01','prompt':'one','start':0,'duration':1000000}]}
            atomic_json(source.folder/'timeline.json',timeline)
            (source.folder/'captions.srt').write_text('captions')
            (source.folder/'audio').mkdir();(source.folder/'audio/narration.wav').write_bytes(b'audio')
            (source.folder/'images').mkdir();(source.folder/'images/001_01.png').write_bytes(b'original')
            source.data.update(installed_path='installed.json',prepared_hashes={'audio/narration.wav':'hash'});source.save()
            target=create_image_repair_copy(source,threading.Event(),lambda _:None,tmp)
            self.assertNotIn('installed_path',target.data)
            self.assertEqual(read_json(target.folder/'timeline.json'),timeline)
            self.assertEqual(target.data['prepared_hashes'],source.data['prepared_hashes'])
            (target.folder/'images/001_01.png').write_bytes(b'corrected')
            self.assertEqual((source.folder/'images/001_01.png').read_bytes(),b'original')
