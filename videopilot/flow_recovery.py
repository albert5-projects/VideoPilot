"""Recover already generated images; never submit or modify a Flow prompt."""
import time
from hashlib import sha256
from contextlib import nullcontext
from . import flow_browser as B
from .flow_concurrent import Tracker,ImageImporter,SWEEP_JS,inspect_next_asset
from .core import UserError,atomic_json,read_json
from .pipeline import cached_image


def recover_queue(job,queue,page,state,path,cancel,log,timeout=None,verify_existing=False,imports_collected=False,order='reverse'):
    # timeout is retained for existing callers; recovery has no overall deadline.
    folder=job.folder/'browser-downloads';folder.mkdir(exist_ok=True)
    if not imports_collected:B.flow.collect_downloads(job,folder)
    def needs_check(shot):
        if not cached_image(job,shot):return True
        meta=read_json(job.folder/'images'/(shot['id']+'.json'))
        return verify_existing and meta.get('source')=='Google Flow browser helper'
    missing=[s for s in queue['shots'] if needs_check(s)]
    if not missing:log('All Flow images are already in the project.');return
    spool=folder/('capture-v3-'+queue['queue_id']);spool.mkdir(exist_ok=True)
    with nullcontext(spool) as temporary:
        def checkpoint():
            records=state.setdefault('inflight',{})
            changed=False
            for sid,item in tracker.active.items():
                record=records.setdefault(sid,{})
                updates={'prompt_hash':sha256(item['shot']['prompt'].encode()).hexdigest(),'generation_ids':sorted(item['ids']),'result_urls':sorted(item['urls'])}
                if any(record.get(k)!=v for k,v in updates.items()):
                    record.update(updates);changed=True
            if changed:
                state['matching_version']=5;atomic_json(path,state)
        tracker=Tracker(page,queue,temporary,set(),checkpoint)
        from .flow_navigation import RecoveryNavigation
        tracker.recovery_navigation=RecoveryNavigation(page,state,path,order,verify_existing)
        for shot in missing:
            tracker.add(shot)
            record=state.get('inflight',{}).get(shot['id'],{})
            trusted=not verify_existing and state.get('matching_version')==5 and record.get('prompt_hash')==sha256(shot['prompt'].encode()).hexdigest()
            tracker.active[shot['id']]['ids'].update(record.get('generation_ids',[]) if trusted else [])
            tracker.active[shot['id']]['urls'].update(url for url in (record.get('result_urls',[]) if trusted else []) if isinstance(url,str) and url.startswith('https://'))
            receipt=folder/'VideoPilot'/queue['queue_id']/(shot['id']+'.receipt.json')
            if receipt.is_file():
                evidence=read_json(receipt)
                expected=sha256(B.normalize(shot['prompt']).encode()).hexdigest()
                if not verify_existing and evidence.get('matching_version')==5 and evidence.get('prompt_hash')==expected:
                    for variant in evidence.get('variants',[]):
                        tracker.active[shot['id']]['urls'].update(url for url in variant.get('result_urls',[]) if isinstance(url,str) and url.startswith('https://'))
        page.on('request',tracker.requested);page.on('requestfinished',tracker.finished);page.on('download',tracker.downloaded)
        if verify_existing:log('Rechecking automatic image assignments against Flow prompts. Replaced images will be backed up; manual selections are retained.')
        log('Recovering existing Flow images only; no Generate clicks. Recovery continues until all required images are imported or you press Stop. Keep the original Flow project open.')
        importer=ImageImporter(job,folder,log,replace_existing=True)
        try:
            # Open the first history panel before decoding the disk spool or
            # attempting network reads of previously saved result URLs.
            B.guard(page,cancel)
            history_gallery=bool(page.locator('flow-editor-page,flow-grid-tile-container').count())
            if history_gallery:inspect_next_asset(page,tracker,advance_completed=True)
            sweep_interval=.25 if history_gallery else 1.
            tracker.restore();last_sweep=time.monotonic();last_retry=last_sweep;last_progress=last_sweep
            while tracker.active:
                B.guard(page,cancel);importer.poll();found,_=tracker.observe()
                if tracker.fatal:raise UserError(tracker.fatal)
                for sid,item in list(tracker.active.items()):
                    images=found.get(sid,{});keys=tuple(sorted(images));now=time.monotonic()
                    if keys!=item['stable']:item['stable']=keys;item['since']=now
                    if len(images)<queue['outputs'] or now-item['since']<0.5:continue
                    B.save_results(job,queue,item['shot'],[dict(im,data=im['path'].read_bytes()) for im in images.values()],import_now=False)
                    importer.submit(item['shot'])
                    tracker.release(sid);state.get('inflight',{}).pop(sid,None)
                    if state.get('pending')==sid:state['pending']=next(iter(state.get('inflight',{})),None)
                    atomic_json(path,state)
                    log(f'Recovered Flow shot {sid}; importing in the background.')
                if tracker.active:
                    if time.monotonic()-last_sweep>=sweep_interval:
                        inspect_next_asset(page,tracker,advance_completed=True);last_sweep=time.monotonic()
                    if time.monotonic()-last_retry>=1:
                        tracker.read_attempts.clear();last_retry=time.monotonic()
                    if time.monotonic()-last_progress>=15:
                        log(f'Flow recovery: {len(tracker.active)} shot(s) still awaiting identified images; {len(importer.pending)} image set(s) importing. Continuing; press Stop to pause.')
                        last_progress=time.monotonic()
                    page.wait_for_timeout(250)
            while importer.pending:
                B.guard(page,cancel);importer.poll()
                if importer.pending:page.wait_for_timeout(100)
            if importer.failures:raise UserError('Recovery could not import: '+', '.join(importer.failures))
        finally:
            page.remove_listener('request',tracker.requested);page.remove_listener('requestfinished',tracker.finished);page.remove_listener('download',tracker.downloaded)
            importer.close()
            # A failed worker's receipt is retried synchronously after it exits.
            B.flow.collect_downloads(job,folder,shot_ids=set(importer.pending)|set(importer.failures),replace_existing=True)
            try:spool.rmdir()
            except OSError:pass
