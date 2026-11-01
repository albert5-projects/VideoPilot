import base64,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from videopilot import flow,flow_browser as B,flow_concurrent as C,pipeline
from videopilot.core import Settings,Job,atomic_json,read_json,Cancelled,UserError
from test_flow_browser import png


def request(prompt=None,url='https://flow.google.com/generate',body=None,kind='application/json'):
    r=Mock(method='POST' if prompt is not None else 'GET',resource_type='fetch',url=url,redirected_from=None)
    r.post_data=json.dumps({'requests':[{'prompt':prompt}]}) if prompt is not None else None
    response=Mock(ok=True,headers={'content-type':kind});response.body.return_value=body
    r.response.return_value=response
    return r


class ConcurrentTests(unittest.TestCase):
    def setUp(self):
        timing=patch.object(C.random,'uniform',return_value=6.0)
        self.random_interval=timing.start();self.addCleanup(timing.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job=Job.create(Settings(idea='Concurrent',aspect='1:1',flow_outputs=1),self.root)
        self.shots=[{'id':f'001_0{i}','prompt':f'Original prompt {i}'} for i in (1,2)]
        atomic_json(self.job.folder/'timeline.json',{'shots':self.shots})
        self.q=flow.queue_for(self.job,{'shots':self.shots});self.cancel=threading.Event()
        self.visible=[];self.cards=[];self.page=Mock()
        self.page.evaluate.side_effect=lambda script,*args:self.visible if script==B.ASSETS_JS else self.cards
        self.tracker=C.Tracker(self.page,self.q,self.root,{'https://old'},lambda:None)
    def tearDown(self):self.tmp.cleanup()

    def start(self,shot):
        self.tracker.add(shot);r=request(shot['prompt']);self.tracker.requested(r);return r
    def finish(self,r,url,color):
        r.response().body.return_value=json.dumps({'media':[{'image':{'fifeUrl':url}}]}).encode()
        self.tracker.finished(r)
        self.tracker.finished(request(url=url,body=png(color=color),kind='image/png'))
        self.visible.append(url)

    def test_reversed_results_are_assigned_to_exact_original_prompt(self):
        first=self.start(self.shots[0]);second=self.start(self.shots[1])
        self.finish(second,'https://images/second','red')
        found,_=self.tracker.observe();self.assertFalse(found['001_01']);self.assertEqual(len(found['001_02']),1)
        self.finish(first,'https://images/first','blue')
        found,_=self.tracker.observe()
        self.assertEqual(next(iter(found['001_01'].values()))['path'].read_bytes(),B.decode_image(png(color='blue'),'1:1')['data'])
        self.assertEqual(next(iter(found['001_02'].values()))['path'].read_bytes(),B.decode_image(png(color='red'),'1:1')['data'])
        self.assertTrue(all('data' not in image for image in self.tracker.images.values()))

    def test_nested_result_prompt_overrides_generating_request(self):
        first=self.start(self.shots[0]);self.start(self.shots[1])
        first.response().body.return_value=json.dumps({'payload':{'result':{
            'prompt':self.shots[1]['prompt'],'imageUrl':'https://images/second'}}}).encode()
        self.tracker.finished(first)
        self.assertFalse(self.tracker.active['001_01']['urls'])
        self.assertEqual(self.tracker.active['001_02']['urls'],{'https://images/second'})

    def test_prompt_in_image_metadata_keeps_sibling_url(self):
        self.start(self.shots[0]);self.start(self.shots[1])
        self.tracker._poll_results({'imageUrl':'https://images/second','metadata':{'prompt':self.shots[1]['prompt']}})
        self.assertFalse(self.tracker.active['001_01']['urls'])
        self.assertEqual(self.tracker.active['001_02']['urls'],{'https://images/second'})

    def test_gallery_advances_past_unrelated_asset_after_loading_grace(self):
        page=Mock();page.locator.return_value.count.return_value=1
        page.evaluate.return_value=[]
        page.locator.return_value.evaluate_all.return_value=['unrelated-1234567890','wanted-123456789012']
        self.tracker.inspect_id='unrelated-1234567890';self.tracker.inspect_opened=0
        with patch.object(C.time,'monotonic',return_value=2):C.inspect_next_asset(page,self.tracker)
        page.get_by_role.assert_not_called()
        with patch.object(C.time,'monotonic',return_value=4):C.inspect_next_asset(page,self.tracker)
        self.assertIn('unrelated-1234567890',self.tracker.inspected_assets)
        self.assertEqual(self.tracker.inspect_id,'wanted-123456789012')

    def test_recovery_advances_completed_history_without_loading_grace(self):
        page=Mock();page.locator.return_value.count.return_value=1
        page.evaluate.return_value=[{'proof':'history-step','owner':'001_01','ids':['finished-1234567890']}]
        page.locator.return_value.evaluate_all.return_value=['wanted-123456789012']
        self.tracker.inspect_opened=0
        with patch.object(C.time,'monotonic',return_value=.5):
            C.inspect_next_asset(page,self.tracker,advance_completed=True)
        page.get_by_role.return_value.click.assert_called_once()
        self.assertEqual(self.tracker.inspect_id,'wanted-123456789012')

    def test_recovery_keeps_loading_grace_for_uncaptured_history(self):
        page=Mock();page.locator.return_value.count.return_value=1
        self.tracker.add(self.shots[0]);self.tracker.inspect_opened=0
        page.evaluate.return_value=[{'proof':'history-step','owner':'001_01','ids':['waiting-1234567890']}]
        with patch.object(C.time,'monotonic',return_value=.5):
            C.inspect_next_asset(page,self.tracker,advance_completed=True)
        page.get_by_role.assert_not_called()

    def test_old_or_changed_browser_receipts_are_not_imported(self):
        shot=self.shots[0]
        B.save_results(self.job,self.q,shot,[B.decode_image(png(),'1:1')],import_now=False)
        root=self.job.folder/'browser-downloads'/'VideoPilot'/self.q['queue_id']
        receipt=root/(shot['id']+'.receipt.json');data=read_json(receipt)
        data['matching_version']=4;atomic_json(receipt,data)
        self.assertEqual(flow.collect_downloads(self.job),0)
        data['matching_version']=5;atomic_json(receipt,data)
        (root/data['variants'][0]['filename']).write_bytes(png(color='red'))
        self.assertEqual(flow.collect_downloads(self.job),0)

    def test_later_unlinked_status_records_recover_missing_generation_metadata(self):
        self.start(self.shots[0]);self.start(self.shots[1])
        response=request(url='https://flow.google.com/gallery',body=json.dumps({'results':[
            {'prompt':self.shots[1]['prompt'],'imageUrl':'https://images/second'},
            {'prompt':'unrelated','imageUrl':'https://images/other'},
            {'prompt':self.shots[0]['prompt'],'imageUrl':'https://images/first'}]}).encode())
        self.tracker.finished(response)
        self.assertEqual(self.tracker.active['001_01']['urls'],{'https://images/first'})
        self.assertEqual(self.tracker.active['001_02']['urls'],{'https://images/second'})

    def test_json_wrapped_response_preserves_result_identity(self):
        r=self.start(self.shots[0])
        r.response().body.return_value=json.dumps({'payload':json.dumps({'imageUrl':'https://images/wrapped'})}).encode()
        self.tracker.finished(r)
        self.assertEqual(self.tracker.active['001_01']['urls'],{'https://images/wrapped'})

    def test_matched_visible_card_recovers_cached_image_without_response(self):
        self.start(self.shots[0]);self.start(self.shots[1])
        self.visible=['https://images/cached','https://images/unrelated']
        self.cards=[{'urls':[url],'ids':[],'owner':'001_01' if url.endswith('cached') else None} for url in self.visible]
        reads=[]
        def evaluate(script,*args):
            if script==B.ASSETS_JS:return self.visible
            if script==C.CARDS_JS:return self.cards
            reads.append(args[0]);return base64.b64encode(png()).decode()
        self.page.evaluate.side_effect=evaluate
        found,_=self.tracker.observe();self.tracker.observe()
        self.assertEqual(reads,['https://images/cached'])
        self.assertEqual(len(found['001_01']),1);self.assertFalse(found['001_02'])

    def test_extra_linked_results_are_saved_and_collected_from_browser_folder(self):
        images=[B.decode_image(png(color=color),'1:1') for color in ('red','blue')]
        B.save_results(self.job,self.q,self.shots[0],images,import_now=False)
        self.assertFalse(pipeline.cached_image(self.job,self.shots[0]))
        self.assertEqual(flow.collect_downloads(self.job),1)
        self.assertTrue(pipeline.cached_image(self.job,self.shots[0]))
        self.assertTrue((self.job.folder/'flow_variants'/self.shots[0]['id']/'v2.png').is_file())
        self.assertEqual(flow.collect_downloads(self.job),0)

    def test_extra_linked_results_do_not_stop_queue(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness()
        observe=C.Tracker.observe
        def extra(tracker):
            found,visible=observe(tracker)
            for sid,images in found.items():
                if images:
                    images['extra-result']=dict(next(iter(images.values())))
            return found,visible
        with patch.object(C.Tracker,'observe',extra),patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(len(clicks),2)
        self.assertTrue(all(pipeline.cached_image(self.job,s) for s in self.shots))
        self.assertFalse(B.pending_shots(self.job))

    def test_extra_calibration_word_is_not_accepted_as_exact_prompt(self):
        self.tracker.add(self.shots[0]);r=request('temporary '+self.shots[0]['prompt'])
        self.tracker.requested(r)
        self.assertFalse(self.tracker.active['001_01']['ack'])

    def test_recovery_imports_after_old_deadline_without_generate_or_reordering(self):
        from videopilot.flow_recovery import recover_queue
        page=Mock();clock=[0.]
        page.locator.return_value.count.return_value=0
        def wait(ms):
            clock[0]+=ms/1000
            threading.Event().wait(.001)
        page.wait_for_timeout.side_effect=wait
        urls=['https://images/second','https://images/first']
        cards=[{'urls':[url],'ids':[],'owner':sid} for url,sid in zip(urls,['001_02','001_01'])]
        def evaluate(script,*args):
            if script==C.SWEEP_JS:return False
            if script==B.ASSETS_JS:return urls if clock[0]>=95 else []
            if script==C.CARDS_JS:return cards if clock[0]>=95 else []
            return base64.b64encode(png(color='red' if args[0]==urls[0] else 'blue')).decode()
        page.evaluate.side_effect=evaluate
        state={'pending':'001_01','inflight':{s['id']:{} for s in self.shots}}
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'):
            recover_queue(self.job,self.q,page,state,B.state_path(self.job,self.q),self.cancel,lambda _:None,timeout=5)
        page.locator.return_value.click.assert_not_called();page.keyboard.insert_text.assert_not_called()
        self.assertTrue(all(pipeline.cached_image(self.job,s) for s in self.shots))
        self.assertFalse(state['inflight']);self.assertIsNone(state['pending'])
        self.assertGreaterEqual(clock[0],95)

    def test_recovery_does_not_resubmit_unidentified_results(self):
        from videopilot.flow_recovery import recover_queue
        page=Mock();page.evaluate.return_value=[];clock=[0.]
        page.locator.return_value.count.return_value=0
        def wait(ms):
            clock[0]+=ms/1000
            if clock[0]>=95:self.cancel.set()
        page.wait_for_timeout.side_effect=wait
        state={'pending':'001_01','inflight':{'001_01':{}}}
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard',side_effect=lambda p,c:B.check_cancel(c)):
            with self.assertRaises(Cancelled):
                recover_queue(self.job,self.q,page,state,B.state_path(self.job,self.q),self.cancel,lambda _:None,timeout=1)
        self.assertGreaterEqual(clock[0],95)
        self.assertEqual(state['pending'],'001_01');page.locator.return_value.click.assert_not_called()

    def test_recovery_opens_history_before_restoring_spool_or_reading_images(self):
        from videopilot import flow_recovery as R
        page=Mock();page.locator.return_value.count.return_value=1
        steps=[]
        def restore():
            steps.append('restore');raise Cancelled('Stopped')
        with patch.object(B,'guard'),patch.object(R,'inspect_next_asset',side_effect=lambda *a,**kw:steps.append('inspect')),patch.object(C.Tracker,'restore',side_effect=restore),patch.object(C.Tracker,'observe') as observe:
            with self.assertRaises(Cancelled):
                R.recover_queue(self.job,self.q,page,{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(steps,['inspect','restore'])
        observe.assert_not_called()

    def test_image_can_arrive_before_generation_metadata_without_guessing(self):
        r=self.start(self.shots[0]);self.start(self.shots[1]);url='https://images/late-identity'
        self.tracker.finished(request(url=url,body=png(),kind='image/png'));self.visible.append(url)
        found,_=self.tracker.observe();self.assertTrue(all(not values for values in found.values()))
        r.response().body.return_value=json.dumps({'images':[{'url':url}]}).encode();self.tracker.finished(r)
        found,_=self.tracker.observe();self.assertEqual(len(found['001_01']),1);self.assertFalse(found['001_02'])

    def test_conflicting_url_is_never_assigned_by_arrival_order(self):
        first=self.start(self.shots[0]);second=self.start(self.shots[1])
        self.finish(first,'https://images/shared','blue');self.finish(second,'https://images/shared','blue')
        found,_=self.tracker.observe();self.assertTrue(self.tracker.fatal)
        self.assertTrue(all(not values for values in found.values()))

    def test_visible_blob_joins_identified_network_image_by_pixels(self):
        r=self.start(self.shots[0]);self.start(self.shots[1])
        r.response().body.return_value=json.dumps({'imageUrl':'https://images/first'}).encode();self.tracker.finished(r)
        self.tracker.finished(request(url='https://images/first',body=png(),kind='image/png'))
        self.visible=['blob:https://flow.google.com/visible']
        self.page.evaluate.side_effect=lambda script,*args:self.visible if script==B.ASSETS_JS else self.cards if script==C.CARDS_JS else base64.b64encode(png()).decode()
        found,_=self.tracker.observe();self.assertEqual(len(found['001_01']),1);self.assertFalse(found['001_02'])

    def test_unlinked_download_and_unrelated_requests_are_ignored(self):
        self.tracker.add(self.shots[0])
        for r in (request('Unrelated prompt'),request(self.shots[0]['prompt'],url='https://analytics.example/collect')):
            self.tracker.requested(r)
        self.assertFalse(self.tracker.active['001_01']['ack'])
        download=Mock(url='https://images/unlinked');self.tracker.downloaded(download);download.save_as.assert_not_called()

    def test_ids_exclude_project_context_and_match_asset_url_tokens(self):
        urls,ids=C.identities({'project':{'id':'project-1234567890'},'clientContext':{'generationId':'wrong-1234567890'},
            'media':[{'name':'projects/example/media/generation-1234567890'}]})
        self.assertEqual(ids,{'generation-1234567890'})
        self.start(self.shots[0]);self.tracker.active['001_01']['ids']=ids
        self.assertEqual(self.tracker.owners({'https://images/generation-1234567890?size=large'}),{'001_01'})
        self.assertFalse(self.tracker.owners({'https://images/other-generation-1234567890-extra'}))

    def test_batched_poll_results_keep_each_operation_separate(self):
        ids=['generation-1234567890','generation-9876543210']
        for shot,identifier in zip(self.shots,ids):
            r=self.start(shot);r.response().body.return_value=json.dumps({'name':'operations/'+identifier}).encode();self.tracker.finished(r)
        poll=request(url='https://flow.google.com/status',body=json.dumps({'operations':[
            {'name':'operations/'+ids[1],'result':{'imageUrl':'https://images/second'}},
            {'name':'operations/'+ids[0],'result':{'imageUrl':'https://images/first'}},
            {'name':'operations/unrelated-1234567890','result':{'imageUrl':'https://images/unrelated'}}]}).encode())
        poll.method='POST';poll.post_data=json.dumps({'operationNames':ids});self.tracker.requested(poll);self.tracker.finished(poll)
        self.assertEqual(self.tracker.active['001_01']['urls'],{'https://images/first'})
        self.assertEqual(self.tracker.active['001_02']['urls'],{'https://images/second'})
        self.tracker._poll_results({'media':[{'name':ids[0],'imageUrl':'https://images/first'},
            {'name':'unrelated-1234567890','imageUrl':'https://images/unrelated'}]})
        self.assertEqual(self.tracker.active['001_01']['urls'],{'https://images/first'})

    def test_multi_output_results_and_unrelated_assets_stay_separate(self):
        r=self.start(self.shots[0]);self.start(self.shots[1])
        r.response().body.return_value=json.dumps({'images':[{'url':'https://images/a'},{'url':'https://images/b'}]}).encode();self.tracker.finished(r)
        for url,color in [('https://images/a','red'),('https://images/b','green'),('https://unrelated','blue')]:
            self.tracker.finished(request(url=url,body=png(color=color),kind='image/png'));self.visible.append(url)
        found,_=self.tracker.observe();self.assertEqual(len(found['001_01']),2);self.assertFalse(found['001_02'])

    def test_linked_native_download_does_not_require_a_visible_url(self):
        self.start(self.shots[0]);self.tracker.active['001_01']['urls'].add('https://images/download')
        download=Mock(url='https://images/download');download.save_as.side_effect=lambda path:Path(path).write_bytes(png())
        self.tracker.downloaded(download);found,_=self.tracker.observe()
        self.assertEqual(len(found['001_01']),1)

    def test_identified_network_result_is_collected_after_card_leaves_view(self):
        r=self.start(self.shots[0]);self.start(self.shots[1])
        self.finish(r,'https://images/offscreen','blue');self.visible.clear()
        self.tracker.finished(request(url='https://images/unrelated',body=png(color='red'),kind='image/png'))
        found,_=self.tracker.observe()
        self.assertEqual(len(found['001_01']),1);self.assertFalse(found['001_02'])

    def test_recovery_capture_has_no_image_count_limit(self):
        image=B.decode_image(png(),'1:1')
        for index in range(49):
            self.tracker._store(dict(image,hash=f'{index:064x}'),{f'https://images/{index}'})
        self.assertIsNone(self.tracker.fatal);self.assertEqual(len(self.tracker.images),49)
        self.assertEqual(len(list(self.root.glob('*.png'))),49)

    def harness(self,ack=True,fail_second=False,stop=False,delays=None,max_active=2):
        clock=[0.];handlers={};events=[];clicks=[];saved=[];current=[''];visible=[]
        page=Mock();field=Mock();button=Mock();button.count.return_value=1;button.is_enabled.return_value=True;button.get_attribute.return_value=None
        field.evaluate.side_effect=lambda _:current[0]
        absent=Mock();absent.count.return_value=0
        page.locator.side_effect=lambda selector:field if selector=='#p' else button if selector=='#g' else absent
        page.evaluate.side_effect=lambda script,*args:list(visible) if script==B.ASSETS_JS else []
        page.on.side_effect=lambda event,handler:handlers.setdefault(event,[]).append(handler)
        page.remove_listener.side_effect=lambda event,handler:handlers[event].remove(handler)
        def emit(event,item):
            for handler in list(handlers.get(event,[])):handler(item)
        def click(**kwargs):
            if kwargs.get('trial'):return
            index=len(clicks);sid=self.shots[index]['id'];state=read_json(B.state_path(self.job,self.q))
            self.assertIn(sid,state['inflight']);self.assertLessEqual(len(state['inflight']),max_active);clicks.append((sid,clock[0]))
            if fail_second and index==1:raise RuntimeError('Click disconnected')
            r=request(current[0])
            if ack:emit('request',r)
            def complete():
                url='https://images/'+sid;r.response().body.return_value=json.dumps({'images':[{'url':url}]}).encode()
                emit('requestfinished',r);emit('requestfinished',request(url=url,body=png(color='blue' if index==0 else 'red'),kind='image/png'));visible.append(url)
            events.append((clock[0]+(delays[index] if delays else 6 if index==0 else .5),complete))
        button.click.side_effect=click
        def wait(ms):
            clock[0]+=ms/1000
            # Let the real disk importer run while the browser clock advances.
            threading.Event().wait(.002)
            for event in list(events):
                if event[0]<=clock[0]:events.remove(event);event[1]()
            if stop and len(clicks)==2:self.cancel.set()
        page.wait_for_timeout.side_effect=wait
        original=B.save_results
        def save(*args,**kwargs):saved.append(args[2]['id']);return original(*args,**kwargs)
        def fill(_page,_selector,text,_cancel):current[0]=text
        return page,clock,clicks,saved,save,fill,handlers

    def test_submission_only_retains_metadata_without_capturing_or_importing(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[.1,500])
        self.random_interval.return_value=8.35
        logs=[]
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'decode_image') as decode,patch.object(C.Tracker,'observe') as observe,patch.object(C.Tracker,'restore') as restore,patch.object(C,'ImageImporter') as importer,patch.object(B,'save_results') as save:
            C.submit_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,logs.append)
        self.assertAlmostEqual(clicks[1][1]-clicks[0][1],8.35,delta=.1)
        self.assertAlmostEqual(clicks[0][1],6,delta=.1)
        self.assertLess(clock[0],15)
        decode.assert_not_called();observe.assert_not_called();restore.assert_not_called();importer.assert_not_called();save.assert_not_called()
        page.evaluate.assert_not_called()
        state=read_json(B.state_path(self.job,self.q))
        self.assertEqual(state['inflight']['001_01']['result_urls'],['https://images/001_01'])
        self.assertEqual(B.pending_shots(self.job),['001_01','001_02'])
        self.assertFalse((self.job.folder/'browser-downloads').exists())
        self.assertTrue(all(not values for values in handlers.values()))
        self.assertTrue(any('Recover generated images' in line for line in logs))

    def test_submission_only_timing_does_not_wait_for_ack_or_images(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(ack=False,delays=[500,500])
        self.random_interval.return_value=10.65
        pasted=[]
        def slow_fill(*args):
            clock[0]+=.8;fill(*args);pasted.append(clock[0])
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=slow_fill):
            C.submit_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertAlmostEqual(clicks[0][1]-pasted[0],6,delta=.1)
        self.assertAlmostEqual(clicks[1][1]-clicks[0][1],10.65,delta=.1)
        self.assertEqual(B.pending_shots(self.job),['001_01','001_02'])

    def test_submission_only_sequential_waits_for_metadata_without_capture(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[3,500])
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'decode_image') as decode:
            C.submit_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':1},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertAlmostEqual(clicks[0][1],6,delta=.1)
        self.assertGreaterEqual(clicks[1][1]-clicks[0][1],3);self.assertLess(clock[0],10)
        decode.assert_not_called();self.random_interval.assert_not_called()

    def test_scheduler_submits_second_before_first_finishes_and_saves_reverse_order(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness()
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard',side_effect=lambda p,c:B.check_cancel(c)),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'save_results',side_effect=save):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertLess(clicks[1][1],6);self.assertEqual(saved,['001_02','001_01'])
        self.assertFalse(B.pending_shots(self.job));self.assertTrue(all(pipeline.cached_image(self.job,s) for s in self.shots))
        self.assertTrue(all(not values for values in handlers.values()))
        self.assertFalse(list((self.job.folder/'browser-downloads').glob('capture-*')))

    def test_uncertain_second_click_retains_both_submissions(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(fail_second=True)
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill):
            with self.assertRaisesRegex(RuntimeError,'disconnected'):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(B.pending_shots(self.job),['001_01','001_02'])
        with patch.object(B,'connect') as connect:
            with self.assertRaisesRegex(UserError,'unresolved'):B.run(self.job,self.cancel,lambda _:None)
            connect.assert_not_called()
        self.assertTrue(all(not values for values in handlers.values()))

    def test_stop_retains_all_inflight_and_requires_explicit_retry(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(stop=True)
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard',side_effect=lambda p,c:B.check_cancel(c)),patch.object(B,'fill_prompt',side_effect=fill):
            with self.assertRaises(Cancelled):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(B.pending_shots(self.job),['001_01','001_02']);B.clear_pending(self.job);self.assertFalse(B.pending_shots(self.job))

    def test_hidden_request_payload_never_uses_arrival_order(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(ack=False)
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'wait_results') as fallback:
            with self.assertRaisesRegex(UserError,'timed out'):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':1},{},B.state_path(self.job,self.q),self.cancel,lambda _:None,timeout=5)
        fallback.assert_not_called();self.assertFalse(saved)

    def test_disabled_generate_keeps_next_prompt_prepared_and_collects_existing_work(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness()
        button=page.locator('#g');button.is_enabled.side_effect=lambda:not clicks or clock[0]>=2
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill) as filling,patch.object(B,'save_results',side_effect=save):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(filling.call_count,2);self.assertGreaterEqual(clicks[1][1],2);self.assertLess(clicks[1][1],6)

    def test_existing_work_is_not_retried_after_timeout(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[500,500])
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill):
            with self.assertRaisesRegex(UserError,'timed out'):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None,timeout=1)
        self.assertEqual(len(clicks),2);self.assertEqual(B.pending_shots(self.job),['001_01','001_02'])

    def test_third_submission_waits_for_a_free_slot(self):
        self.shots.append({'id':'001_03','prompt':'Original prompt 3'})
        atomic_json(self.job.folder/'timeline.json',{'shots':self.shots});self.q=flow.queue_for(self.job,{'shots':self.shots})
        page,clock,clicks,saved,save,fill,handlers=self.harness()
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'save_results',side_effect=save):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertGreaterEqual(clicks[2][1],clicks[1][1]+1.0)
        self.assertEqual(saved,['001_02','001_03','001_01'])

    def test_identical_prompts_are_not_inflight_together(self):
        self.shots[1]['prompt']=self.shots[0]['prompt']
        atomic_json(self.job.folder/'timeline.json',{'shots':self.shots});self.q=flow.queue_for(self.job,{'shots':self.shots})
        page,clock,clicks,saved,save,fill,handlers=self.harness()
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'save_results',side_effect=save):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','parallel':2},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertGreaterEqual(clicks[1][1],6.5);self.assertEqual(saved,['001_01','001_02'])

    def test_timed_mode_randomizes_each_delay_without_ack_or_finished_images(self):
        self.random_interval.side_effect=[6.35,10.75,8.125]
        self.shots.append({'id':'001_03','prompt':'Original prompt 3'})
        atomic_json(self.job.folder/'timeline.json',{'shots':self.shots});self.q=flow.queue_for(self.job,{'shots':self.shots})
        page,clock,clicks,saved,save,fill,handlers=self.harness(ack=False,delays=[30,30,30],max_active=3)
        advance=page.wait_for_timeout.side_effect
        def stop_after_three(ms):
            advance(ms)
            if len(clicks)==3:self.cancel.set()
        page.wait_for_timeout.side_effect=stop_after_three
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard',side_effect=lambda p,c:B.check_cancel(c)),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'wait_results') as fallback:
            with self.assertRaises(Cancelled):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6,'parallel':0},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(len(clicks),3)
        for previous,current,delay in zip(clicks,clicks[1:],[6.35,10.75]):
            self.assertAlmostEqual(current[1]-previous[1],delay,delta=.1)
        self.assertEqual(self.random_interval.call_count,3)
        self.assertTrue(all(call.args==(6.0,11.0) for call in self.random_interval.call_args_list))
        fallback.assert_not_called();self.assertEqual(B.pending_shots(self.job),['001_01','001_02','001_03'])

    def test_timed_collection_imports_second_while_first_still_generates(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[20,.5])
        imports=[];original=B.flow.collect_downloads
        def collect(*args,**kwargs):
            result=original(*args,**kwargs);imports.append((kwargs['shot_ids'],clock[0]));return result
        logs=[]
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B,'save_results',side_effect=save),patch.object(B.flow,'collect_downloads',side_effect=collect):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6,'parallel':0},{},B.state_path(self.job,self.q),self.cancel,logs.append)
        self.assertAlmostEqual(clicks[1][1]-clicks[0][1],6,delta=.1)
        self.assertEqual(saved,['001_02','001_01'])
        self.assertEqual([entry[0] for entry in imports],[{'001_02'},{'001_01'}])
        self.assertLess(imports[0][1],20)
        self.assertEqual(sum(line.startswith('Imported Flow shot') for line in logs),2)
        self.assertTrue(all(pipeline.cached_image(self.job,s) for s in self.shots))

    def test_slow_import_does_not_block_six_second_submissions(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[.1,20])
        started=threading.Event();release=threading.Event();original=B.flow.collect_downloads
        def collect(*args,**kwargs):
            started.set()
            if not release.wait(5):raise AssertionError('Submission blocked behind import')
            return original(*args,**kwargs)
        advance=page.wait_for_timeout.side_effect
        def wait(ms):
            advance(ms)
            if len(clicks)==2:
                self.assertTrue(started.is_set());release.set()
        page.wait_for_timeout.side_effect=wait
        try:
            with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B.flow,'collect_downloads',side_effect=collect):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        finally:release.set()
        self.assertAlmostEqual(clicks[1][1]-clicks[0][1],6,delta=.1)
        self.assertTrue(all(pipeline.cached_image(self.job,s) for s in self.shots))

    def test_import_failure_retains_receipt_for_recovery(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[.1,20])
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill),patch.object(B.flow,'collect_downloads',side_effect=OSError('Disk full')):
            with self.assertRaisesRegex(OSError,'Disk full'):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertTrue((self.job.folder/'browser-downloads'/'VideoPilot'/self.q['queue_id']/'001_01.receipt.json').exists())
        flow.collect_downloads(self.job,self.job.folder/'browser-downloads')
        self.assertTrue(pipeline.cached_image(self.job,self.shots[0]))

    def test_stop_finishes_import_of_already_captured_image(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[.1,20])
        advance=page.wait_for_timeout.side_effect
        def wait(ms):
            advance(ms)
            if clock[0]>=4:self.cancel.set()
        page.wait_for_timeout.side_effect=wait
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard',side_effect=lambda p,c:B.check_cancel(c)),patch.object(B,'fill_prompt',side_effect=fill):
            with self.assertRaises(Cancelled):
                C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,lambda _:None)
        self.assertEqual(len(clicks),1)
        self.assertTrue(pipeline.cached_image(self.job,self.shots[0]))
        self.assertFalse(pipeline.cached_image(self.job,self.shots[1]))

    def test_timed_mode_reports_site_disabled_button_instead_of_forcing_click(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(delays=[20,.5])
        page.locator('#g').is_enabled.side_effect=lambda:not clicks or clock[0]>=9
        logs=[]
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6,'parallel':0},{},B.state_path(self.job,self.q),self.cancel,logs.append)
        self.assertGreaterEqual(clicks[1][1],9);self.assertLess(clicks[1][1],9.5)
        self.assertTrue(any('Generate is unavailable' in line for line in logs))

    def test_pending_results_are_imported_by_automatic_gallery_pass(self):
        page,clock,clicks,saved,save,fill,handlers=self.harness(ack=False,delays=[1,1])
        evaluate=page.evaluate.side_effect;swept=[False];logs=[]
        def scan(script,*args):
            if script==C.SWEEP_JS:swept[0]=True;return True
            if script==C.CARDS_JS and swept[0]:
                return [{'urls':[url],'ids':[],'owner':url.rsplit('/',1)[-1]} for url in evaluate(B.ASSETS_JS)]
            return evaluate(script,*args)
        page.evaluate.side_effect=scan
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),patch.object(B,'guard'),patch.object(B,'fill_prompt',side_effect=fill):
            C.run_queue(self.job,self.q,self.shots,page,{'prompt':'#p','generate':'#g','interval':6},{},B.state_path(self.job,self.q),self.cancel,logs.append)
        self.assertTrue(swept[0]);self.assertEqual(len(clicks),2)
        self.assertTrue(all(pipeline.cached_image(self.job,shot) for shot in self.shots))
        self.assertTrue(any('generated but unimported' in line for line in logs))

    def test_import_worker_retries_transient_failure_without_generating(self):
        B.save_results(self.job,self.q,self.shots[0],[B.decode_image(png(),'1:1')],import_now=False)
        original=B.flow.collect_downloads;calls=[];logs=[]
        def collect(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:raise OSError('temporary file lock')
            return original(*args,**kwargs)
        with patch.object(B.flow,'collect_downloads',side_effect=collect):
            importer=C.ImageImporter(self.job,self.job.folder/'browser-downloads',logs.append)
            try:
                importer.submit(self.shots[0])
                import time
                end=time.monotonic()+5
                while importer.pending and time.monotonic()<end:
                    importer.poll();threading.Event().wait(.01)
                self.assertFalse(importer.pending);self.assertFalse(importer.failures)
            finally:importer.close()
        self.assertEqual(len(calls),2);self.assertTrue(pipeline.cached_image(self.job,self.shots[0]))

    def test_wrapped_and_form_encoded_prompts_and_delayed_request_keep_identity(self):
        from urllib.parse import urlencode
        first=self.shots[0];second=self.shots[1]
        self.tracker.add(first);self.tracker.add(second)
        r=request(first['prompt']);r.post_data=urlencode({'f.req':json.dumps({'payload':json.dumps({'parts':[{'text':first['prompt']}]})})})
        self.tracker.requested(r)
        self.assertTrue(self.tracker.active[first['id']]['ack']);self.assertFalse(self.tracker.active[second['id']]['ack'])
        self.finish(r,'https://images/first','blue');found,_=self.tracker.observe()
        self.assertEqual(len(found[first['id']]),1);self.assertFalse(found[second['id']])
        self.tracker.active[first['id']]['ids'].add('reference-1234567890')
        followup=request(second['prompt']);followup.post_data=json.dumps({'prompt':second['prompt'],'referenceMediaId':'reference-1234567890'})
        self.tracker.requested(followup);self.assertEqual(self.tracker.requests[followup],second['id'])


if __name__=='__main__':unittest.main()
