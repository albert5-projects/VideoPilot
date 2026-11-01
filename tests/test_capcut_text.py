import copy,json,tempfile,unittest
from pathlib import Path
from videopilot.capcut import Template,parse_text_content,replace_text_content
from videopilot.core import Settings,UserError,atomic_json
from test_system import fixture,wav

# Structural reproduction of the supplied 2.1.0 text run, with generic text/path.
LEGACY='<outline color=(0,0,0,1) width=0.084><b><size=15><font id="" path="C:/Fonts/en.ttf">[Sample caption]</font></size></b></outline>'

class CapCutTextTests(unittest.TestCase):
    def test_legacy_replacement_preserves_all_style_tags_and_unicode(self):
        text="A baker's story — café 🥖\nSecond line"
        actual=replace_text_content(LEGACY,text)
        self.assertEqual(actual,LEGACY.replace('[Sample caption]','['+text+']'))
        self.assertEqual(parse_text_content(actual)[1]['text'],text)

    def test_json_text_still_updates_utf16_range_and_preserves_style(self):
        raw=json.dumps({'text':'old','styles':[{'range':[0,3],'size':15,'bold':True}]})
        actual=json.loads(replace_text_content(raw,'Bread 🥖'))
        self.assertEqual(actual['text'],'Bread 🥖')
        self.assertEqual(actual['styles'],[{'range':[0,8],'size':15,'bold':True}])

    def test_unsupported_or_ambiguous_styles_are_rejected(self):
        for raw in ['[]','null','{"text":"x","styles":null}',LEGACY.replace('</b>','</i>'),'<font>[one]</font><font>[two]</font>']:
            with self.subTest(raw=raw),self.assertRaises(UserError):parse_text_content(raw)
        for text in ['Hello [world]','<b>caption</b>']:
            with self.assertRaises(UserError):replace_text_content(LEGACY,text)

    def test_native_style_and_unique_wav_build_without_extra_mp3_materials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'template'/'draft_content.json';data=fixture(path)
            data['materials']['texts'][0].update(content=LEGACY,font_size=15.0,border_color='#000000')
            data['materials']['audios'].append({'id':'music','path':'sample.mp3','type':'extract_music'})
            extra=copy.deepcopy(data['tracks'][1]);extra['id']='music-track';extra['segments'][0].update(id='music-segment',material_id='music')
            data['tracks'].insert(0,extra) # Music need not appear after the WAV.
            atomic_json(path,data);original=path.read_bytes();template=Template(path)
            self.assertEqual(template.samples['audio'][1]['material_id'],'a')
            wav(root/'audio'/'narration.wav',1)
            from PIL import Image
            (root/'images').mkdir();Image.new('RGB',(600,600)).save(root/'images'/'001_01.png')
            timeline={'duration':1000000,'width':600,'height':600,'shots':[{'id':'001_01','start':0,'duration':1000000}],
                      'captions':[{'start':0,'duration':1000000,'text':'Fresh bread'}],'overlays':[]}
            draft=template.build(timeline,root,Settings(idea='test',aspect='1:1',bgm='none',sfx=False))
            self.assertEqual(len(draft['materials']['audios']),1)
            self.assertEqual(Path(draft['materials']['audios'][0]['path']).name,'narration.wav')
            text=draft['materials']['texts'][0]
            self.assertIn('[Fresh bread]',text['content']);self.assertIn('path="C:/Fonts/en.ttf"',text['content'])
            self.assertLess(text['font_size'],15.0);self.assertEqual(text['border_color'],'#101722')
            self.assertEqual(path.read_bytes(),original)

    def test_two_wav_tracks_require_unambiguous_template(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'draft_content.json';data=fixture(path)
            extra=copy.deepcopy(data['tracks'][1]);extra['id']='another-audio';data['tracks'].append(extra)
            atomic_json(path,data)
            with self.assertRaisesRegex(UserError,'exactly one local WAV'):Template(path)

if __name__=='__main__':unittest.main()
