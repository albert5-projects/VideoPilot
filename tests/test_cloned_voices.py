import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import numpy as np
from videopilot import cloned_voices as cv
from videopilot.core import Settings, Job, UserError, atomic_json, file_hash, read_json
from videopilot.nano_voice import NanoVoice
from videopilot.tts_worker import main


class ClonedVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch.object(cv, 'LIBRARY', self.root/'voices');p.start();self.addCleanup(p.stop)

    def sample(self, seconds=10):
        path = self.root/'sample.wav'
        samples = (.2*np.sin(np.arange(24000*seconds)*.05)*32767).astype('<i2')
        with wave.open(str(path), 'wb') as w:
            w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(samples.tobytes())
        return path

    def test_import_list_remove_preserves_project_sample(self):
        voice = cv.add_voice(self.sample(), 'Grandmother')
        self.assertIn(voice, cv.voices().values())
        with patch.object(cv, 'worker_python', return_value='python'):
            job = Job.create(Settings(idea='Story',voice=voice),root=self.root/'projects')
        saved = cv.reference(voice,job.folder);digest=file_hash(saved)
        cv.remove_voice(voice)
        self.assertNotIn(voice,cv.voices().values())
        self.assertEqual(file_hash(cv.reference(voice,job.folder)),digest)
        with self.assertRaises(UserError):cv.reference(voice)

    def test_short_sample_rejected_without_library_entry(self):
        with self.assertRaises(UserError):cv.add_voice(self.sample(3),'Short')
        self.assertEqual(cv.voices(),{})
        self.assertEqual(list(cv.LIBRARY.glob('*.wav')),[])

    def test_missing_runtime_and_path_traversal_rejected(self):
        with patch.object(cv,'RUNTIME',self.root/'missing.exe'):
            with self.assertRaises(UserError):cv.worker_python('nano_'+'a'*32)
        with self.assertRaises(UserError):cv.reference('../../outside')
        self.assertFalse(cv.is_nano('am_michael'))

    def test_nano_worker_cache_and_reference_invalidation(self):
        voice=cv.add_voice(self.sample(),'Test');reference=cv.reference(voice)
        folder=self.root/'audio';folder.mkdir();req=self.root/'request.json'
        request={'folder':str(folder),'reference':str(reference),'voice':voice,
                 'language':'en-us','speed':1.,'scenes':['Hello there.']}
        atomic_json(req,request)
        class FakeNano:
            calls=0
            loads=0
            def __init__(self,request,progress):
                FakeNano.loads+=1
                self.request=request;self.reference_hash=file_hash(request['reference'])
            signature=NanoVoice.signature
            def create(self,*args,**kwargs):
                FakeNano.calls+=1
                return .2*np.sin(np.arange(24000)*.05).astype(np.float32),24000
        with patch('videopilot.nano_voice.NanoVoice',FakeNano):
            self.assertEqual(main(req),0);first=file_hash(folder/'001.wav')
            self.assertEqual(main(req),0);self.assertEqual(FakeNano.calls,1)
            self.assertEqual(FakeNano.loads,1)
            reference.write_bytes(reference.read_bytes()+b'new reference')
            self.assertEqual(main(req),0);self.assertEqual(FakeNano.calls,2)
            self.assertEqual(FakeNano.loads,2)
            self.assertEqual(file_hash(folder/'001.wav'),first)
        self.assertTrue(read_json(folder/'progress.json')['done'])


if __name__=='__main__':unittest.main()
