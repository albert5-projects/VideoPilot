import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Job,Settings
from videopilot.storage import clean_duplicates,share_identical_file

class StorageLinkTests(unittest.TestCase):
    def test_dedup_keeps_all_paths_and_excludes_edited_images_and_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(Settings(idea='Storage'),tmp)
            files=[]
            for folder in ('flow_variants/001_01','browser-downloads/capture-v3-test','browser-downloads/VideoPilot/test','images','backups'):
                path=job.folder/folder/'image.png';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original');files.append(path)
            self.assertEqual(clean_duplicates(job),16)
            self.assertTrue(all(p.exists() for p in files))
            self.assertTrue(files[0].samefile(files[1]));self.assertTrue(files[0].samefile(files[2]))
            self.assertFalse(files[0].samefile(files[3]));self.assertFalse(files[0].samefile(files[4]))
            self.assertEqual(clean_duplicates(job),0)
            files[1].unlink();self.assertEqual(files[0].read_bytes(),b'original')

    def test_unsupported_links_and_different_bytes_leave_copies_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a';b=Path(tmp)/'b';a.write_bytes(b'one');b.write_bytes(b'one')
            with patch('videopilot.storage.os.link',side_effect=OSError('Unsupported')):
                self.assertEqual(share_identical_file(a,b),0)
            self.assertEqual(b.read_bytes(),b'one');self.assertFalse(a.samefile(b))
            b.write_bytes(b'two');self.assertEqual(share_identical_file(a,b),0)
            self.assertEqual(b.read_bytes(),b'two')
