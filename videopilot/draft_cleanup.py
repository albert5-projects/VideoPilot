"""Explicit repair of visible stars in media referenced by a CapCut draft."""
from copy import copy,deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os,shutil,tempfile,time,uuid
from PIL import Image
from .core import UserError,atomic_json,read_json,file_hash
from .image_cleanup import clean_visible_star,CLEANUP_VERSION
from . import capcut


def remove_draft_stars(job,cancel,log):
    if job.settings.video_editor!='capcut':raise UserError('This repair is for CapCut drafts.')
    if capcut.capcut_running():raise UserError('Close CapCut before repairing draft images, then reopen the draft afterward.')
    draft=Path(job.data.get('installed_path') or job.folder/'capcut'/'draft_content.json')
    if not draft.is_file():raise UserError('Build the CapCut draft first.')
    lock=job.folder/'run.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise UserError('Stop the current project operation before repairing draft images.') from None
    os.close(fd)
    try:return _repair(job,draft,cancel,log)
    finally:lock.unlink(missing_ok=True)


def _repair(job,draft,cancel,log):
    before_draft=file_hash(draft);content=read_json(draft)
    used={segment.get('material_id') for track in content.get('tracks',[]) for segment in track.get('segments',[])}
    references={Path(item['path']).resolve() for item in content.get('materials',{}).get('videos',[])
                if item.get('id') in used and item.get('path')}
    report_path=job.folder/'graphics_report.json'
    graphics=read_json(report_path) if report_path.is_file() else {'clips':{}}
    clips={sid:clip for sid,clip in graphics.get('clips',{}).items() if Path(clip['path']).resolve() in references}
    sources={path for path in references if path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp')}
    sources.update((job.folder/'images'/f'{sid}.png').resolve() for sid in clips)
    cache_path=job.folder/'DRAFT_STAR_REPAIR.json'
    cache=read_json(cache_path) if cache_path.is_file() else {'images':{}}
    checked=cache.get('images',{});changes={};records={};hashes={}
    log(f'Checking {len(sources)} draft image(s) for remaining corner stars; verified images are skipped.')
    with tempfile.TemporaryDirectory(prefix='star-repair-',dir=job.folder) as temporary:
        work=Path(temporary)
        def scan(pair):
            index,path=pair;job.check(cancel)
            if not path.is_file():raise UserError('Draft source image is missing: '+str(path))
            before=file_hash(path);key=str(path)
            if checked.get(key)=={'sha256':before,'version':CLEANUP_VERSION}:return path,before,None,None
            with Image.open(path) as source:
                fmt=source.format;cleaned,info=clean_visible_star(source)
            staged=None
            if info['status']=='cleaned':
                staged=work/f'image-{index}{path.suffix}';cleaned.save(staged,format=fmt)
            return path,before,staged,info
        # Two workers bound memory/CPU; repaired pixels are staged on disk.
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='draft-star') as worker:
            for path,before,staged,info in worker.map(scan,enumerate(sorted(sources))):
                job.check(cancel);hashes[path]=before
                records[str(path)]={'sha256':file_hash(staged) if staged else before,'version':CLEANUP_VERSION}
                if staged:
                    changes[path]=staged
                    log('Removing remaining star: '+path.name)
                    meta=path.with_suffix('.json')
                    if path.parent==(job.folder/'images').resolve() and meta.is_file():
                        data=read_json(meta);data.update(sha256=records[str(path)]['sha256'],visible_star_cleanup=info)
                        staged_meta=work/f'{path.stem}-metadata.json';atomic_json(staged_meta,data);changes[meta]=staged_meta
        affected=[sid for sid in clips if (job.folder/'images'/f'{sid}.png').resolve() in changes]
        if affected:
            for sid in affected:
                target=Path(clips[sid]['path']).resolve();hashes[target]=file_hash(target)
            _render_affected(job,affected,clips,changes,work,cancel,log)
            updated=deepcopy(graphics)
            for sid in affected:
                updated['clips'][sid]['source_image_sha256']=records[str((job.folder/'images'/f'{sid}.png').resolve())]['sha256']
            staged_report=work/'graphics_report.json';atomic_json(staged_report,updated);changes[report_path]=staged_report
        job.check(cancel)
        if capcut.capcut_running() or file_hash(draft)!=before_draft:
            raise UserError('CapCut opened or the draft changed. Close CapCut and retry; no repaired media was installed.')
        if any(file_hash(path)!=before for path,before in hashes.items()):
            raise UserError('Source media changed during repair. Retry; no repaired media was installed.')
        if changes:
            backup=job.folder/'backups'/('star-repair-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            backup.mkdir(parents=True)
            manifest=[]
            for index,path in enumerate(changes):
                saved=backup/f'{index}{path.suffix}'
                if path.is_file():shutil.copy2(path,saved)
                manifest.append({'path':str(path),'backup':str(saved) if saved.is_file() else None})
            atomic_json(backup/'manifest.json',manifest)
            applied=[]
            try:
                for entry in manifest:
                    job.check(cancel);path=Path(entry['path'])
                    # Stage beside the destination so replacement is atomic even
                    # when the CapCut media resides on another volume.
                    sibling=path.with_name(path.name+'.star-repair-'+uuid.uuid4().hex+'.tmp')
                    try:
                        shutil.copy2(changes[path],sibling);os.replace(sibling,path)
                    finally:sibling.unlink(missing_ok=True)
                    applied.append(entry)
            except BaseException:
                for entry in reversed(applied):
                    path=Path(entry['path'])
                    if entry['backup']:shutil.copy2(entry['backup'],path)
                    else:path.unlink(missing_ok=True)
                raise
            log('Original media backed up in '+str(backup))
        atomic_json(cache_path,{'images':records,'repaired_images':sum(path in changes for path in sources),'rebuilt_graphics':affected})
        count=sum(path in changes for path in sources)
        log(f'Draft star repair complete: {count} image(s) repaired; {len(sources)-count} skipped; {len(affected)} graphics clip(s) rebuilt. Reopen the draft in CapCut.')
        return count


def _render_affected(job,affected,clips,changes,work,cancel,log):
    """Reuse saved overlays and edit decisions; never request new planning."""
    from .remotion_graphics import render_graphics
    from .overlay_planner import validate_overlay
    timeline_path=job.folder/'edit_timeline.json'
    if not timeline_path.is_file():raise UserError('Saved edit decisions are missing; graphics cannot be repaired without changing the edit.')
    timeline=read_json(timeline_path);shots=[shot for shot in timeline['shots'] if shot['id'] in affected]
    if len(shots)!=len(affected):raise UserError('The saved edit does not match the draft graphics.')
    plans={}
    for shot in shots:
        sid=shot['id'];path=job.folder/'overlay-plans'/f'{sid}.json'
        if clips[sid].get('source_shot_id')!=sid or clips[sid].get('source_image_sha256')!=file_hash(job.folder/'images'/f'{sid}.png'):
            raise UserError(f'Graphics source for {sid} does not match the current image. No media was changed.')
        if not path.is_file():raise UserError(f'Saved overlay plan for {sid} is missing. No media was changed.')
        plans[sid]=validate_overlay(read_json(path)['plan'],shot['duration']/1e6)
        if not plans[sid]['elements']:raise UserError(f'The saved overlay plan for {sid} does not match its rendered clip.')
    # A staging-only Job lets the existing renderer operate without modifying
    # the installed project's state, media, report or saved editing decisions.
    staging=copy(job);staging.folder=work/'render';staging.folder.mkdir()
    staging.path=staging.folder/'job.json';staging.data=dict(job.data);staging.data.pop('installed_path',None)
    (staging.folder/'images').mkdir()
    for shot in shots:
        path=(job.folder/'images'/f'{shot["id"]}.png').resolve()
        shutil.copy2(changes[path],staging.folder/'images'/path.name)
    log(f'Rebuilding only {len(shots)} affected graphics clip(s), reusing saved plans.')
    rendered=render_graphics(staging,read_json(job.folder/'script.json'),timeline,cancel,log,
                             selected_shots=shots,planned_overlays=plans)
    for sid in affected:
        target=Path(clips[sid]['path']).resolve();clip=Path(rendered['clips'][sid]['path'])
        changes[target]=clip
        if target.with_suffix('.json').is_file():
            changes[target.with_suffix('.json')]=clip.with_suffix('.json')
