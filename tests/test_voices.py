import tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
from videopilot.voices import english_voices


class VoiceTests(unittest.TestCase):
    def test_setup_without_model_offers_all_28_english_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            voices=english_voices(Path(tmp)/'missing.bin')
        self.assertEqual(len(voices),28)
        self.assertEqual(voices['Michael \u00b7 US male'],'am_michael')
        self.assertEqual(sum(v.startswith('a') for v in voices.values()),20)
        self.assertEqual(sum(v.startswith('b') for v in voices.values()),8)

    def test_only_installed_english_entries_are_listed_without_loading_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'voices.bin'
            with ZipFile(path,'w') as archive:
                for name in ('af_nova.npy','bm_lewis.npy','am_future_voice.npy','jf_alpha.npy','../../af_fake.npy','readme.txt'):
                    archive.writestr(name,b'Not an array: only the archive index should be read')
            voices=english_voices(path)
        self.assertEqual(set(voices.values()),{'af_nova','bm_lewis','am_future_voice'})
        self.assertEqual(voices['Future Voice \u00b7 US male'],'am_future_voice')

    def test_corrupt_archive_keeps_gui_usable_for_model_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'voices.bin';path.write_bytes(b'partial download')
            self.assertEqual(len(english_voices(path)),28)

if __name__=='__main__':unittest.main()
