import copy,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Settings,UserError,Cancelled,atomic_json,validate_plan
from videopilot.providers import GeneratedPlanError,plan_video
from test_system import PLAN


class ScriptRepairTests(unittest.TestCase):
    def test_blank_and_oversized_narration_have_distinct_messages(self):
        plan=copy.deepcopy(PLAN);plan['scenes'][-1]['narration']=' '
        with self.assertRaisesRegex(UserError,'Scene 2: narration is empty'):validate_plan(plan)
        plan['scenes'][-1]['narration']='x'*601
        with self.assertRaisesRegex(UserError,'601 characters; split'):validate_plan(plan)

    def test_repair_receives_saved_draft_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);original=copy.deepcopy(PLAN);original['scenes'][-1]['narration']=''
            atomic_json(folder/'response.json',original);before=(folder/'response.json').read_bytes()
            with patch('videopilot.providers.run_codex',side_effect=[GeneratedPlanError('Scene 2: narration is empty.'),PLAN]) as run:
                result=plan_video(Settings(idea='test'),folder,threading.Event())
            self.assertEqual(result,PLAN);self.assertEqual(run.call_count,2)
            args=run.call_args_list[1].args
            self.assertEqual(args[1],folder/'repair');self.assertIn('narration is empty',args[0])
            self.assertIn(original['scenes'][0]['narration'],args[0])
            self.assertEqual((folder/'response.json').read_bytes(),before)

    def test_repair_is_bounded_to_one_attempt(self):
        with tempfile.TemporaryDirectory() as tmp,patch('videopilot.providers.run_codex',side_effect=GeneratedPlanError('narration is empty')) as run:
            with self.assertRaisesRegex(UserError,'after one automatic repair'):
                plan_video(Settings(idea='test'),Path(tmp),threading.Event())
            self.assertEqual(run.call_count,2)

    def test_account_errors_and_cancellation_are_not_retried(self):
        for error in (UserError('Account quota exceeded'),Cancelled('Stopped')):
            with tempfile.TemporaryDirectory() as tmp,patch('videopilot.providers.run_codex',side_effect=error) as run:
                with self.assertRaises(type(error)):plan_video(Settings(idea='test'),Path(tmp),threading.Event())
                self.assertEqual(run.call_count,1)
        cancel=threading.Event();cancel.set()
        with tempfile.TemporaryDirectory() as tmp,patch('videopilot.providers.run_codex',side_effect=GeneratedPlanError('blank')) as run:
            with self.assertRaises(Cancelled):plan_video(Settings(idea='test'),Path(tmp),cancel)
            self.assertEqual(run.call_count,1)
