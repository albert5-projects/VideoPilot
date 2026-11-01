import tempfile,unittest,json
from pathlib import Path
from videopilot.core import split_caption
from videopilot.text_layout import fit_text,style_text
from videopilot.cached_effects import native_transition

class MotionStyleTests(unittest.TestCase):
    def test_existing_caption_reflow_preserves_audio_range_and_is_idempotent(self):
        from videopilot.text_layout import reflow_captions
        source=[{'text':'Prepare the shelter carefully before starting the next set of movements','start':123456,'duration':2345678}]
        result=reflow_captions(source,'9:16')
        self.assertEqual(result[0]['start'],source[0]['start'])
        self.assertEqual(sum(c['duration'] for c in result),source[0]['duration'])
        self.assertEqual(' '.join(c['text'] for c in result),source[0]['text'])
        self.assertEqual(reflow_captions(result,'9:16'),result)

    def test_caption_chunks_preserve_every_word_and_limit_normal_phrases(self):
        text='Prepare the shelter carefully before starting the next set of movements'
        chunks=split_caption(text,max_chars=24)
        self.assertEqual(' '.join(chunks),text)
        self.assertTrue(all(len(s)<=24 and len(s.split())<=5 for s in chunks))

    def test_long_text_fits_both_aspects_without_dropping_content(self):
        from PIL import ImageFont
        for width,height in ((1080,1920),(1920,1080),(1080,1080)):
            text='ExtraordinarilyLongTechnicalTerm '+('A long educational caption ' * 6)
            fitted,size=fit_text(text,width,height)
            self.assertEqual(fitted.split(),text.split())
            font=ImageFont.load_default(size=max(1,round(size*6)))
            self.assertTrue(all(font.getlength(line)<width*.8 for line in fitted.splitlines()))
            self.assertLess(len(fitted.splitlines())*size*6*1.3,height*.14)

    def test_emphasis_is_distinct_from_captions(self):
        a={'content':json.dumps({'text':'sample','styles':[{'range':[0,6],'size':15}]})};b=dict(a)
        style_text(a,'Listen closely',1080,1920);style_text(b,'LISTEN CLOSELY',1080,1920,True)
        self.assertNotEqual(a['text_color'],b['text_color']);self.assertNotEqual(a['italic_degree'],b['italic_degree'])
        self.assertGreater(b['font_size'],a['font_size'])

    def test_cache_reuse_requires_native_reference_and_existing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'Cache/effect/123/package';package.mkdir(parents=True)
            draft=root/'Projects/com.lveditor.draft/sample/draft_content.json';draft.parent.mkdir(parents=True)
            material={'id':'fx','name':'Woosh','type':'transition','path':str(package)}
            data={'materials':{'transitions':[material]},'tracks':[{'type':'video','segments':[{'extra_material_refs':['fx']}]}]}
            draft.write_text(json.dumps(data));self.assertEqual(native_transition(root),material)
            data['tracks']=[];draft.write_text(json.dumps(data));self.assertIsNone(native_transition(root))
            data['tracks']=[{'type':'video','segments':[{'extra_material_refs':['fx']}]}]
            data['materials']['transitions'][0]['path']=str(root);draft.write_text(json.dumps(data));self.assertIsNone(native_transition(root))

if __name__=='__main__':unittest.main()
