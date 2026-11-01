import base64, io, tempfile, threading, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from videopilot import flow, flow_browser as B, pipeline
from videopilot.core import Job, Settings, UserError, Cancelled, atomic_json, read_json


def png(size=(600,600),color='blue'):
    out=io.BytesIO();Image.new('RGB',size,color).save(out,'PNG');return out.getvalue()


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.job=Job.create(Settings(idea='Browser',aspect='1:1',flow_outputs=1),self.root)
        self.shots=[{'id':'001_01','prompt':'Original first prompt'}, {'id':'001_02','prompt':'Original second prompt'}]
        atomic_json(self.job.folder/'timeline.json',{'shots':self.shots})
        self.q=flow.queue_for(self.job,{'shots':self.shots});self.cancel=threading.Event()
        self.image=B.decode_image(png(),'1:1')
    def tearDown(self):self.temp.cleanup()

    def test_flow_scope(self):
        for url in ['https://labs.google/fx/tools/flow','https://labs.google/fx/en/tools/flow/project/a','https://flow.google.com/project/a']:
            self.assertTrue(B.allowed_page(url))
        for url in ['https://accounts.google.com','https://evil.example','https://flow.google.com.evil.example','https://labs.google/fx/tools/whisk']:
            self.assertFalse(B.allowed_page(url))

    def test_refresh_clears_cookies_cache_and_flow_data_without_changing_submissions(self):
        page=Mock();session=page.context.new_cdp_session.return_value
        atomic_json(B.state_path(self.job,self.q),{'pending':'001_01'})
        before=B.state_path(self.job,self.q).read_bytes()
        @contextmanager
        def connection(cancel):yield page
        logs=[]
        with patch.object(B,'connect',connection):B.refresh_browser(self.cancel,logs.append)
        self.assertEqual([call.args for call in session.send.call_args_list],[
            ('Network.clearBrowserCache',),
            ('Network.clearBrowserCookies',),
            ('Storage.clearDataForOrigin',{'origin':'https://labs.google','storageTypes':'all'}),
            ('Storage.clearDataForOrigin',{'origin':'https://flow.google.com','storageTypes':'all'}),
            ('Network.setCacheDisabled',{'cacheDisabled':True}),
            ('Network.setBypassServiceWorker',{'bypass':True}),
            ('Network.setCacheDisabled',{'cacheDisabled':False}),
            ('Network.setBypassServiceWorker',{'bypass':False})])
        page.reload.assert_called_once_with(wait_until='domcontentloaded',timeout=60000)
        page.evaluate.assert_called_once_with('()=>sessionStorage.clear()')
        session.detach.assert_called_once()
        self.assertEqual(B.state_path(self.job,self.q).read_bytes(),before)
        self.assertTrue(logs)

    def test_refresh_restores_network_settings_after_reload_failure(self):
        page=Mock();page.reload.side_effect=RuntimeError('Reload failed')
        session=page.context.new_cdp_session.return_value
        @contextmanager
        def connection(cancel):yield page
        with patch.object(B,'connect',connection):
            with self.assertRaisesRegex(RuntimeError,'Reload failed'):B.refresh_browser(self.cancel,lambda _:None)
        self.assertEqual(session.send.call_args.args,('Network.setBypassServiceWorker',{'bypass':False}))
        session.detach.assert_called_once()

    def test_refresh_cancel_does_not_connect(self):
        self.cancel.set()
        with patch.object(B,'connect') as connection:
            with self.assertRaises(Cancelled):B.refresh_browser(self.cancel,lambda _:None)
        connection.assert_not_called()

    def test_browser_reuses_endpoint_without_launching_or_reading_cookies(self):
        with patch.object(B,'endpoint',return_value='http://127.0.0.1:12345'),patch.object(B.subprocess,'Popen') as launch:
            self.assertEqual(B.open_browser(profile=self.root),'http://127.0.0.1:12345');launch.assert_not_called()

    def test_browser_launch_always_uses_dedicated_profile(self):
        with patch.object(B,'profile_processes',return_value=[]),patch.object(B,'endpoint',side_effect=[None,'http://127.0.0.1:12345']),patch.object(B,'browser_executable',return_value=Path('chrome.exe')),patch.object(B.subprocess,'Popen') as launch:
            B.open_browser(profile=self.root/'dedicated')
            args=launch.call_args.args[0]
            self.assertIn('--user-data-dir='+str((self.root/'dedicated').resolve()),args)
            self.assertIn('--remote-debugging-address=127.0.0.1',args)
            self.assertNotIn('--headless',args)

    def test_manual_signin_launch_has_no_automation_or_security_override_flags(self):
        profile=self.root/'sign in profile'
        with patch.object(B,'profile_processes',return_value=[]),patch.object(B,'endpoint',return_value=None),patch.object(B,'browser_executable',return_value=Path('chrome.exe')),patch.object(B.subprocess,'Popen') as launch:
            B.open_signin_browser(profile=profile)
            self.assertEqual(launch.call_args.args[0],['chrome.exe',f'--user-data-dir={profile.resolve()}','--no-first-run',flow.FLOW_URL])

    def test_signin_cannot_reuse_an_existing_automation_browser(self):
        with patch.object(B,'profile_processes',return_value=[{'ProcessId':123}]),patch.object(B.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(UserError,'Close all VideoPilot browser windows'):
                B.open_signin_browser(profile=self.root)
            launch.assert_not_called()

    def test_signin_refuses_live_debug_endpoint_even_without_process_match(self):
        with patch.object(B,'profile_processes',return_value=[]),patch.object(B,'endpoint',return_value='http://127.0.0.1:12345'),patch.object(B.subprocess,'Popen') as launch:
            with self.assertRaises(UserError):B.open_signin_browser(profile=self.root)
            launch.assert_not_called()

    def test_queue_cannot_attach_to_manual_signin_browser(self):
        with patch.object(B,'profile_processes',return_value=[{'ProcessId':123}]),patch.object(B,'endpoint',return_value=None),patch.object(B.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(UserError,'Close the dedicated sign-in browser'):
                B.open_browser(profile=self.root)
            launch.assert_not_called()

    def test_signin_fails_closed_when_process_inspection_fails(self):
        with patch.object(B,'profile_processes',side_effect=UserError('Cannot check browser')),patch.object(B.subprocess,'Popen') as launch:
            with self.assertRaises(UserError):B.open_signin_browser(profile=self.root)
            launch.assert_not_called()

    def test_signin_stop_never_opens_browser(self):
        self.cancel.set()
        with patch.object(B.subprocess,'Popen') as launch:
            with self.assertRaises(Cancelled):B.open_signin_browser(self.cancel,profile=self.root)
            launch.assert_not_called()

    def test_unusual_activity_stops_before_further_browser_actions(self):
        page=Mock(url='https://flow.google.com/project/example')
        for message in ['Failed. We noticed some unusual activity. Note that browser extensions that modify the page may cause issues.', 'Browser extensions that modify the page may cause issues.']:
            page.locator.return_value.inner_text.return_value=message
            with self.subTest(message=message),self.assertRaisesRegex(UserError,'Queue stopped'):
                B.guard(page,self.cancel)
        page.keyboard.insert_text.assert_not_called()

    def test_bad_endpoint_file_does_not_connect(self):
        (self.root/'DevToolsActivePort').write_text('80\n/evil')
        with patch.object(B,'build_opener') as http:
            self.assertIsNone(B.endpoint(self.root));http.assert_not_called()

    def test_validation_rejects_unsafe_and_duplicate_shots(self):
        for q in [{**self.q,'queue_id':'../../bad'}, {**self.q,'shots':[{'id':'../bad','prompt':'x'}]}, {**self.q,'shots':[self.shots[0]]*2}]:
            with self.assertRaises(UserError):B.validate_queue(q)

    def test_decode_enforces_size_ratio_and_content(self):
        self.assertIsNotNone(self.image)
        self.assertIsNone(B.decode_image(b'not an image','1:1'))
        self.assertIsNone(B.decode_image(png((256,256)),'1:1'))
        self.assertIsNone(B.decode_image(png((600,1000)),'1:1'))

    def test_prompt_uses_browser_keyboard_and_checks_text_after_blur(self):
        page=Mock();field=Mock();page.locator.return_value=field;field.count.return_value=1
        field.evaluate.side_effect=['','Original prompt','Original prompt']
        with patch.object(B,'guard'):
            B.fill_prompt(page,'#prompt','Original prompt',self.cancel)
        page.keyboard.insert_text.assert_called_once_with('Original prompt')
        self.assertEqual([c.args[0] for c in field.press.call_args_list],['ControlOrMeta+A','Backspace','Tab','Tab'])
        self.assertEqual(field.evaluate.call_count,3)

    def test_calibration_word_must_be_cleared_before_prompt_insert(self):
        page=Mock();field=page.locator.return_value;field.count.return_value=1
        field.evaluate.return_value='temporary word'
        with patch.object(B,'guard'):
            with self.assertRaisesRegex(UserError,'did not clear'):
                B.fill_prompt(page,'#prompt','Original prompt',self.cancel)
        page.keyboard.insert_text.assert_not_called()

    def test_results_wait_for_a_stable_set_and_timeout_without_retry(self):
        page=Mock();page.evaluate.return_value=['https://image/new'];clock=[0.0]
        page.wait_for_timeout.side_effect=lambda ms:clock.__setitem__(0,clock[0]+ms/1000)
        results=Mock(received=1,errors=[]);results.accepted.return_value={'hash':self.image}
        with patch.object(B,'guard'),patch.object(B.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertEqual(B.wait_results(page,results,1,self.cancel,lambda _:None),[self.image])
            self.assertGreaterEqual(clock[0],5)
            results.accepted.return_value={}
            with self.assertRaisesRegex(UserError,'unresolved'):
                B.wait_results(page,results,1,self.cancel,lambda _:None,timeout=1)
        page.locator.assert_not_called()

    def test_capture_matches_redirect_alias_to_visible_asset_and_deduplicates(self):
        r=B.Results(Mock(),'1:1',{'https://images/old'},self.root)
        prior=Mock(url='https://images/new',redirected_from=None)
        request=Mock(url='https://images/final',redirected_from=prior)
        response=Mock(ok=True,headers={'content-type':'image/png'});response.body.return_value=png();request.response.return_value=response
        r.finished(request);r.finished(request)
        self.assertEqual(len(r.accepted({'https://images/new'})),1)
        self.assertEqual(len(r.accepted({'https://images/unrelated'})),0)
        prior.url='https://images/old';r.candidates.clear();r.finished(request)
        self.assertEqual(r.candidates,{})

    def test_native_download_is_validated_and_partial_removed(self):
        r=B.Results(Mock(),'1:1',set(),self.root);download=Mock()
        download.save_as.side_effect=lambda path:Path(path).write_bytes(png())
        r.downloaded(download);self.assertEqual(len(r.accepted(set())),1)
        self.assertFalse((self.root/'browser-download.partial').exists())

    def test_new_visible_blob_captured_once_without_reading_old_or_foreign_blobs(self):
        page=Mock();page.evaluate.return_value=base64.b64encode(png()).decode()
        old='blob:https://labs.google/old';new='blob:https://labs.google/new'
        r=B.Results(page,'1:1',{old},self.root)
        urls=[old,new,'blob:https://evil.example/not-flow']
        r.visible_blobs(urls);r.visible_blobs(urls)
        page.evaluate.assert_called_once();self.assertEqual(page.evaluate.call_args.args[1],new)
        self.assertEqual(len(r.accepted(urls)),1)

    def test_receipt_imports_and_retains_variants(self):
        B.save_results(self.job,self.q,self.shots[0],[self.image])
        self.assertTrue(pipeline.cached_image(self.job,self.shots[0]))
        self.assertTrue((self.job.folder/'flow_variants/001_01/v1.png').is_file())

    def harness(self,fail=False):
        page=Mock();page.evaluate.return_value=[];button=Mock();button.count.return_value=1;page.locator.return_value=button
        clicks=[]
        button.evaluate.side_effect=lambda _:self.shots[len(clicks)]['prompt']
        def click(**kwargs):
            if kwargs.get('trial'):return
            pending=read_json(B.state_path(self.job,self.q))['pending'];clicks.append(pending)
            if fail:raise RuntimeError('Browser disconnected during click')
        button.click.side_effect=click
        @contextmanager
        def connection(cancel):yield page
        return page,clicks,connection

    def test_queue_uses_submission_only_tracker(self):
        page,clicks,connection=self.harness()
        with patch.object(B,'connect',connection),patch.object(B,'calibrate',return_value={'prompt':'#p','generate':'#g'}),patch('videopilot.flow_concurrent.submit_queue') as run:
            B.run(self.job,self.cancel,lambda _:None)
            self.assertEqual(run.call_args.args[2],self.shots)
        self.assertFalse((self.job.folder/'run.lock').exists())

    def test_uncertain_submission_stays_pending_and_cannot_auto_retry(self):
        page,clicks,connection=self.harness(fail=True)
        with patch.object(B,'connect',connection),patch.object(B,'guard'),patch.object(B,'calibrate',return_value={'prompt':'#p','generate':'#g'}),patch.object(B,'fill_prompt'):
            with self.assertRaises(RuntimeError):B.run(self.job,self.cancel,lambda _:None)
            with self.assertRaisesRegex(UserError,'unresolved'):B.run(self.job,self.cancel,lambda _:None)
        self.assertEqual(clicks,['001_01']);self.assertEqual(B.pending_shot(self.job),'001_01')
        B.clear_pending(self.job);self.assertIsNone(B.pending_shot(self.job))

    def test_prompt_failure_never_submits(self):
        page,clicks,connection=self.harness()
        with patch.object(B,'connect',connection),patch.object(B,'guard'),patch.object(B,'calibrate',return_value={'prompt':'#p','generate':'#g'}),patch.object(B,'fill_prompt',side_effect=UserError('Prompt mismatch')):
            with self.assertRaisesRegex(UserError,'Prompt mismatch'):B.run(self.job,self.cancel,lambda _:None)
        self.assertEqual(clicks,[]);self.assertIsNone(B.pending_shot(self.job))

    def test_cancel_releases_lock_without_importing(self):
        page,clicks,connection=self.harness()
        with patch.object(B,'connect',connection),patch.object(B,'calibrate',return_value={'prompt':'#p','generate':'#g'}),patch('videopilot.flow_concurrent.submit_queue',side_effect=Cancelled('Stopped')):
            with self.assertRaises(Cancelled):B.run(self.job,self.cancel,lambda _:None)
        self.assertFalse(pipeline.cached_image(self.job,self.shots[0]))
        self.assertFalse((self.job.folder/'run.lock').exists())


if __name__=='__main__':unittest.main()
