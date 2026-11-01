import json
import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from videopilot.core import split_caption
from videopilot.text_layout import speech_captions,fit_text,style_text,reflow_captions


class SubtitleTests(unittest.TestCase):
    def test_voice_cues_never_reach_subtitles_or_change_narration(self):
        text='[cough] Come on in, honey. [sigh] Sit beside me.'
        self.assertEqual(split_caption(text),['Come on in, honey.','Sit beside me.'])
        captions=speech_captions(text,0,6000000,'16:9')
        self.assertEqual([c['text'] for c in captions],['Come on in, honey.','Sit beside me.'])
        self.assertEqual(sum(c['duration'] for c in captions),6000000)
        cached=reflow_captions([{'text':'[cough] Come on in, honey.','start':0,'duration':2000000}],'16:9')
        self.assertEqual(cached[0]['text'],'Come on in, honey.')
        self.assertEqual(text,'[cough] Come on in, honey. [sigh] Sit beside me.')
        self.assertEqual(split_caption('[COUGH] [laugh]'),[])
        self.assertIn('[optional]',split_caption('Add [optional] honey.')[0])

    def test_sentence_ends_are_hard_boundaries_including_quotes(self):
        text='Come inside. Ready now? Yes! She said “Welcome.” Then smiled… All done.'
        phrases=split_caption(text,max_words=50,max_chars=500)
        self.assertEqual(phrases,['Come inside.','Ready now?','Yes!','She said “Welcome.”','Then smiled…','All done.'])
        self.assertEqual(' '.join(phrases),text)

    def test_long_words_are_never_broken_or_discarded(self):
        text='A remarkablylongunbrokenword followed by ordinary words.'
        phrases=split_caption(text,max_chars=12)
        self.assertEqual(' '.join(phrases),text)
        fitted,size=fit_text(phrases[1],576,1024)
        self.assertEqual(fitted,'remarkablylongunbrokenword')
        self.assertGreater(size,0)

    def test_small_subtitles_and_intact_native_text(self):
        raw=json.dumps({'text':'Old','styles':[{'range':[0,3],'size':15}]})
        material={'content':raw,'force_apply_line_max_width':True}
        style_text(material,'A quiet afternoon.',1920,1080)
        fitted=json.loads(material['content'])
        self.assertEqual(fitted['text'].replace('\n',' '),'A quiet afternoon.')
        self.assertLessEqual(material['font_size']*6,1080*.038+.01)
        self.assertFalse(material['force_apply_line_max_width'])
        self.assertEqual(fitted['styles'][0]['range'],[0,len(fitted['text'])])
        self.assertGreater(fit_text('A quiet afternoon.',1920,1080,emphasis=True)[1],material['font_size'])

    def test_speech_timing_avoids_spending_caption_time_on_long_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'speech.wav';rate=24000
            samples=np.zeros(rate*4,dtype='<i2')
            samples[:rate]=1500;samples[rate*3:]=1500
            with wave.open(str(path),'wb') as out:
                out.setparams((1,2,rate,0,'NONE','not compressed'));out.writeframes(samples.tobytes())
            captions=speech_captions('Hello. There.',500000,4000000,'16:9',path)
        self.assertEqual([c['text'] for c in captions],['Hello.','There.'])
        self.assertGreaterEqual(captions[1]['start'],3500000)
        self.assertEqual(captions[0]['start'],500000)
        self.assertEqual(captions[0]['start']+captions[0]['duration'],captions[1]['start'])
        self.assertEqual(captions[-1]['start']+captions[-1]['duration'],4500000)

    def test_cached_captions_split_sentences_without_changing_coverage(self):
        source=[{'text':'Sit down. Would you like tea?','start':100,'duration':3000000}]
        captions=reflow_captions(source,'16:9')
        self.assertEqual([c['text'] for c in captions],['Sit down.','Would you like tea?'])
        self.assertEqual(sum(c['duration'] for c in captions),3000000)
        self.assertEqual(captions[0]['start'],100)
