import threading,unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Settings,UserError,make_timeline,fingerprint
from videopilot.pipeline import preparation_signature
from videopilot.providers import plan_video
from videopilot.remotion_graphics import EDIT_SETTINGS
from test_system import PLAN

class MinimumHoldTests(unittest.TestCase):
    def test_validation(self):
        for minimum in (0,.5,2,5):Settings(idea='test',min_shot_seconds=minimum).validate()
        for minimum in (-1,.1,6,float('nan'),float('inf')):
            with self.assertRaises(UserError):Settings(idea='test',min_shot_seconds=minimum).validate()

    def test_exact_coverage_and_limits(self):
        timeline=make_timeline(PLAN,[8.2,12.3],Settings(min_shot_seconds=3,shot_seconds=5))
        cursor=0
        for shot in timeline['shots']:
            self.assertEqual(shot['start'],cursor)
            self.assertGreaterEqual(shot['duration'],3000000);self.assertLessEqual(shot['duration'],5000000)
            cursor+=shot['duration']
        self.assertEqual(cursor,20500000)

    def test_impossible_scene_continues_with_smallest_exception(self):
        for durations in ([2,8],[5.5,8]):
            timeline=make_timeline(PLAN,durations,Settings(min_shot_seconds=3,shot_seconds=5))
            self.assertEqual(timeline['shots'][0]['duration'],round(durations[0]*1e6))
            self.assertEqual(len(timeline['image_hold_exceptions']),1)
            baseline=make_timeline(PLAN,durations,Settings(shot_seconds=5))
            self.assertEqual(timeline['captions'],baseline['captions'])
            self.assertEqual(timeline['overlays'],baseline['overlays'])
            self.assertEqual(timeline['duration'],baseline['duration'])

    def test_short_matching_visual_beats_can_share_image(self):
        from copy import deepcopy
        plan=deepcopy(PLAN)
        plan['scenes'][1]['visual']=plan['scenes'][0]['visual']
        plan['scenes'][1]['graphic']=plan['scenes'][0].get('graphic')
        for scene in plan['scenes']:scene['sfx']=False
        timeline=make_timeline(plan,[2,2],Settings(min_shot_seconds=3,shot_seconds=5))
        self.assertEqual(len(timeline['shots']),1)
        self.assertEqual(timeline['shots'][0]['duration'],4000000)
        self.assertEqual(timeline['shots'][0]['source_scenes'],[1,2])
        self.assertEqual(timeline['image_hold_exceptions'],[])
        plan['scenes'][1]['visual']='A completely different location'
        self.assertEqual(len(make_timeline(plan,[2,2],Settings(min_shot_seconds=3,shot_seconds=5))['shots']),2)

    def test_disabled_minimum_preserves_old_signature(self):
        settings=Settings();values=vars(settings).copy();values.pop('min_shot_seconds')
        values.pop('sample_script')
        values.pop('constant_image_prompt')
        for key in ('template_path','sfx_folder')+EDIT_SETTINGS:values.pop(key,None)
        self.assertEqual(preparation_signature(PLAN,settings),fingerprint([PLAN,values]))
        settings.min_shot_seconds=2
        self.assertNotEqual(preparation_signature(PLAN,settings),fingerprint([PLAN,values]))

    def test_script_prompt_uses_requested_cadence(self):
        with patch('videopilot.providers.run_codex',return_value=PLAN) as planner:
            plan_video(Settings(min_shot_seconds=8,shot_seconds=10),Path('.'),threading.Event())
        prompt=planner.call_args.args[0]
        self.assertIn('between 8 and 10 seconds',prompt)
        self.assertNotIn('2-4 seconds',prompt)
        self.assertIn('normally 21 words',prompt)
        self.assertIn('Aim for 7 scenes',prompt)
