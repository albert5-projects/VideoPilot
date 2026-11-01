import copy,json,shutil,subprocess,unittest
import numpy as np
from PIL import Image,ImageDraw
from videopilot.core import Settings,UserError,make_timeline,ROOT
from videopilot.remotion_graphics import graphic_timing
from videopilot.image_cleanup import clean_visible_star,_alpha_template
from test_system import PLAN


class CompositionUpdateTests(unittest.TestCase):
    def test_decimal_hold_is_respected_above_and_below_old_limit(self):
        for limit in (.5,1.25,7.5,120):
            settings=Settings(idea='test',shot_seconds=limit);settings.validate()
            timeline=make_timeline(PLAN,[8.,11.25],settings)
            self.assertLessEqual(max(x['duration'] for x in timeline['shots']),limit*1e6+1)
            self.assertEqual(sum(x['duration'] for x in timeline['shots']),19250000)
        self.assertEqual(len(make_timeline(PLAN,[8.,11.25],Settings(shot_seconds=120))['shots']),2)
        for limit in (0,.49,121,float('inf'),float('nan')):
            with self.assertRaises(UserError):Settings(idea='test',shot_seconds=limit).validate()

    def test_cues_follow_narrated_items_and_account_for_split_shots(self):
        plan=copy.deepcopy(PLAN)
        plan['scenes'][0]['narration']='First water fills the bowl then fire heats the bread'
        graphic={'kind':'process','items':['Water','Fire']}
        timeline=make_timeline(plan,[10,3],Settings(shot_seconds=5))
        self.assertEqual(graphic_timing(plan,timeline['shots'][0],timeline,graphic),[30,140])
        self.assertEqual(graphic_timing(plan,timeline['shots'][1],timeline,graphic),[0,30])

    @unittest.skipUnless(shutil.which('node'),'Node required for actual layout module')
    def test_actual_render_regions_never_overlap_or_cover_caption_area(self):
        module=str(ROOT/'videopilot/remotion_assets/layout.cjs')
        script='const {compositionLayout}=require('+json.dumps(module)+');console.log(JSON.stringify([...[1920,1080,1080].map((w,i)=>[w,[1080,1920,1080][i]])].flatMap(([w,h])=>[1,2].map(s=>({w,h,...compositionLayout(w,h,s)})))));'
        result=json.loads(subprocess.check_output(['node','-e',script],text=True))
        def overlaps(a,b):
            return a['left']<b['left']+b['width'] and b['left']<a['left']+a['width'] and a['top']<b['top']+b['height'] and b['top']<a['top']+a['height']
        for item in result:
            self.assertFalse(overlaps(item['image'],item['graphic']))
            for key in ('image','graphic'):
                region=item[key];self.assertFalse(overlaps(region,item['captions']))
                self.assertGreaterEqual(region['left'],0);self.assertGreaterEqual(region['top'],0)
                self.assertLessEqual(region['left']+region['width'],item['w'])
                self.assertLessEqual(region['top']+region['height'],item['h'])

    def test_translucent_star_on_line_is_removed_without_erasing_whole_line(self):
        image=Image.new('RGB',(768,768),(170,140,100));draw=ImageDraw.Draw(image)
        draw.line((600,675,710,635),fill=(25,30,35),width=5)
        original=np.asarray(image).copy();alpha=np.asarray(_alpha_template(),dtype=float)/255
        x,y=638,638;patch=np.asarray(image.crop((x,y,x+64,y+64)),dtype=float)
        marked=np.rint(patch*(1-alpha[:,:,None])+255*alpha[:,:,None]).astype('uint8')
        image.paste(Image.fromarray(marked),(x,y));before=np.asarray(image).astype(float)
        result,report=clean_visible_star(image);self.assertEqual(report['status'],'cleaned')
        after=np.asarray(result).astype(float)
        self.assertLess(np.mean(abs(after[638:702,638:702]-original[638:702,638:702])),np.mean(abs(before[638:702,638:702]-original[638:702,638:702]))*.65)
        np.testing.assert_array_equal(after[:600],original[:600])

    def test_real_mark_crossing_outline_uses_boundary_fallback(self):
        with Image.open(ROOT/'tests/fixtures/flow-star-on-outline.png') as im:
            cleaned,report=clean_visible_star(im)
            self.assertEqual(report['status'],'cleaned')
            self.assertEqual(report.get('method'),'boundary')
            self.assertLess(abs(report['x']-263),6)
            self.assertLess(abs(report['y']-263),6)
            self.assertNotEqual(cleaned.tobytes(),im.convert('RGB').tobytes())


if __name__=='__main__':unittest.main()
