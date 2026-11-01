import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Settings,Job,UserError,make_timeline,fingerprint
from videopilot.flow import queue_for
from videopilot.pipeline import preparation_matches,preparation_signature
from videopilot.providers import plan_video
from test_system import PLAN


class ConstantImagePromptTests(unittest.TestCase):
    def test_prefix_and_scene_reach_queue_without_global_rules(self):
        plan=copy.deepcopy(PLAN)
        plan['visual_bible']='Hattie appears ONLY in the first and final images. Exactly three ingredients.'
        plan['scenes'][0]['visual']='Hattie, seventy, silver bun, blue blouse, seated by a sunny window.'
        plan['scenes'][1]['visual']='Three amber jars in a linen drawer, overhead view, no people.'
        prefix='Warm window light.\nPhotorealistic still photography.'
        settings=Settings(idea='Story',constant_image_prompt=prefix,shot_seconds=5)
        timeline=make_timeline(plan,[7,4],settings)
        legacy=make_timeline(plan,[7,4],Settings(shot_seconds=5))
        self.assertEqual(timeline['captions'],legacy['captions'])
        self.assertEqual(timeline['duration'],legacy['duration'])
        self.assertEqual([(s['id'],s['start'],s['duration']) for s in timeline['shots']],
                         [(s['id'],s['start'],s['duration']) for s in legacy['shots']])
        with tempfile.TemporaryDirectory() as tmp:
            job=Job.create(settings,tmp);reopened=Job(job.folder)
            self.assertEqual(reopened.settings.constant_image_prompt,prefix)
            queue=queue_for(reopened,timeline)
        for shot in queue['shots']:
            self.assertTrue(shot['prompt'].startswith(prefix+'\n'))
            self.assertEqual(shot['prompt'].count(prefix),1)
            self.assertNotIn(plan['visual_bible'],shot['prompt'])
        self.assertNotIn('Hattie',queue['shots'][-1]['prompt'])
        self.assertIn(plan['scenes'][1]['visual'],queue['shots'][-1]['prompt'])

    def test_blank_prefix_uses_only_scene_and_existing_shot_constraints(self):
        prompt=make_timeline(PLAN,[2,2],Settings(constant_image_prompt=''))['shots'][0]['prompt']
        self.assertTrue(prompt.startswith(PLAN['scenes'][0]['visual']+'\n'))
        self.assertNotIn(PLAN['visual_bible'],prompt)
        self.assertIn('Aspect ratio 9:16',prompt)

    def test_legacy_projects_keep_prompts_and_preparation_cache(self):
        settings=Settings();values=vars(settings).copy();values.pop('constant_image_prompt')
        old=fingerprint([PLAN,values])
        self.assertTrue(preparation_matches(old,PLAN,settings))
        self.assertIn(PLAN['visual_bible'],make_timeline(PLAN,[2,2],settings)['shots'][0]['prompt'])
        self.assertNotEqual(preparation_signature(PLAN,settings),preparation_signature(PLAN,Settings(constant_image_prompt='')))

    def test_planner_gets_constant_and_applies_conditional_rules_per_scene(self):
        settings=Settings(constant_image_prompt='Amber glass, warm sunlight.',
                          details='Only show Hattie in the first and final images.')
        with patch('videopilot.providers.run_codex',return_value=PLAN) as codex:
            plan_video(settings,Path('.'),threading.Event())
        prompt=codex.call_args.args[0]
        self.assertIn('"constant_image_prompt": "Amber glass, warm sunlight."',prompt)
        self.assertIn('Only show Hattie in the first and final images.',prompt)
        self.assertIn('without repeating the constant text or visual_bible',prompt)
        self.assertIn('Never paste the global rule',prompt)

    def test_invalid_prefix_rejected(self):
        for value in (123,'x'*12001):
            with self.assertRaises(UserError):Settings(idea='Test',constant_image_prompt=value).validate()
