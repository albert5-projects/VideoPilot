import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import Settings,Job,UserError
from videopilot.script_reference import read_sample_script
from videopilot.providers import plan_video
from test_system import PLAN

class ScriptReferenceTests(unittest.TestCase):
    def test_reference_is_saved_in_project_and_sent_on_replanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'example.txt';source.write_text('An engaging opening.\nA clear ending.',encoding='utf-8-sig')
            sample=read_sample_script(source)
            job=Job.create(Settings(idea='A different subject',sample_script=sample),tmp)
            source.unlink();reloaded=Job(job.folder)
            with patch('videopilot.providers.run_codex',return_value=PLAN) as codex:
                plan_video(reloaded.settings,job.folder,threading.Event(),feedback='Adjust the duration.')
            prompt=codex.call_args.args[0]
            self.assertIn('An engaging opening.',prompt);self.assertIn('sample_script_reference',prompt)
            self.assertIn('A different subject',prompt);self.assertIn('Do not copy its sentences',prompt)
            self.assertEqual(reloaded.settings.sample_script,sample)

    def test_utf16_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.txt';path.write_text('A sample script.',encoding='utf-16')
            self.assertEqual(read_sample_script(path),'A sample script.')
            path.write_text(' \n ')
            with self.assertRaisesRegex(UserError,'empty'):read_sample_script(path)
            with self.assertRaisesRegex(UserError,'.txt'):read_sample_script(Path(tmp)/'sample.pdf')

    def test_optional_reference_omitted_from_brief(self):
        with patch('videopilot.providers.run_codex',return_value=PLAN) as codex:
            plan_video(Settings(),Path('.'),threading.Event())
        self.assertNotIn('"sample_script_reference":',codex.call_args.args[0])
