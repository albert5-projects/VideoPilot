"""Resumable pipeline; a manifest tracks real outputs rather than fake success."""
from __future__ import annotations
import json, os, shutil, time
from pathlib import Path
from .core import (UserError, Paused, Cancelled, atomic_json, read_json, fingerprint,
                   file_hash, validate_plan, make_timeline)
from .providers import plan_video, gemini_image, get_key
from .audio import synthesize, join_wavs, generated_ambient, generated_whoosh, wav_info, audio_info, background_path
from .capcut import Template


def stamp(us):
    ms=round(us/1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def write_prompts(job,timeline):
    chunks=['IMAGE GENERATION WORK ORDER','Generate ONE image per prompt. Save using the exact filename.','Use your Google Flow browser session. Set IMAGE mode, the matching aspect ratio and output count. No API key is needed.','Import the downloaded image folder in VideoPilot when ready.','']
    for s in timeline['shots']:
        chunks += [f'FILE: {s["id"]}.png',f'TIMELINE: {s["start"]/1e6:.2f}s – {(s["start"]+s["duration"])/1e6:.2f}s',s['prompt'],'']
    (job.folder/'IMAGE_PROMPTS.txt').write_text('\n'.join(chunks),encoding='utf-8')
    if job.settings.video_editor=='kdenlive':
        (job.folder/'EDITOR_HANDOFF.md').write_text('Kdenlive handoff\n\nContinue the project to build kdenlive/VideoPilot.kdenlive.\nUse Open / save Kdenlive project to save a new file in Videos and open it.\nNarration, music, effects and visuals use separate tracks. Subtitles are editable.\nKeep the VideoPilot project folder: the editor references its media and subtitle file.\nReview the timeline, then export in Kdenlive. Codex decisions are saved in editing/edit-plan.json when selected.\n',encoding='utf-8')
        return
    (job.folder/'CAPCUT_HANDOFF.md').write_text(f'''# CapCut handoff — no render/export
Project: {job.folder}
Duration: {timeline['duration']/1e6:.2f} seconds. Canvas: {job.settings.aspect}.
Use the existing old CapCut installation. Never install/update it or modify update-blocking files.
This file is an instruction handoff for an assistant that ALREADY has authorized desktop control. VideoPilot does not embed Astra or provide that control.

1. Use timeline.json, images/, audio/narration.wav and captions.srt.
2. If the legacy template adapter succeeded, install only into a newly created empty project while CapCut is closed, then reopen it.
3. Otherwise import images and arrange them at the exact microsecond timings in timeline.json. If graphics_report.json lists a clip for a shot, use that rendered MP4 in place of its image. Add narration from zero. Do not stretch or cut spoken words.
4. Add music.wav on a separate quiet track (about 12% volume) and effects sparingly at shots marked sfx (about 45%). Adjust by listening; generated ambient is a basic optional drone.
5. Use captions.srt if this CapCut version supports subtitle import, otherwise the caption timings in timeline.json. These are phrase timing estimates, not forced alignment. Fix visibly early/late words.
6. Keep emphasis text clear of subtitles. Image movement enabled: {job.settings.image_motion}. The adapter adds gentle keyframes only when enabled; rendered graphics clips already contain their chosen movement. Avoid duplicate emphasis text over a rendered graphic title.
7. Review every image for narration relevance, continuity, framing, defects and factual accuracy. Replace poor generations. Listen through transitions for pronunciation and joins.
8. Save the editable project, confirm no missing media and all tracks cover the intended duration. Do NOT render, export or publish.
9. Only then use Mark finished in VideoPilot. Never mark it finished from an asset manifest alone.
''',encoding='utf-8')


def image_signature(job,shot):
    return fingerprint([shot['prompt'],job.settings.dimensions,job.settings.image_mode,job.settings.image_model])


def import_images(job,source):
    job.require_mutable()
    from PIL import Image, ImageOps
    if not (job.folder/'timeline.json').exists(): raise UserError('Generate the script and narration first so image timings exist.')
    timeline=read_json(job.folder/'timeline.json'); source=Path(source); destination=job.folder/'images'; destination.mkdir(exist_ok=True)
    count=0
    for shot in timeline['shots']:
        matches=[p for p in source.iterdir() if p.is_file() and p.stem==shot['id'] and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')]
        if not matches: continue
        if len(matches)>1: raise UserError('Multiple images named '+shot['id']+'. Keep one file per shot.')
        path=destination/f'{shot["id"]}.png'
        cleanup={}
        with Image.open(matches[0]) as im:
            im=ImageOps.exif_transpose(im).convert('RGB')
            if job.settings.image_mode=='flow':
                from .image_cleanup import clean_visible_star
                im,cleanup=clean_visible_star(im)
            im=ImageOps.fit(im,job.settings.dimensions,method=Image.Resampling.LANCZOS)
            temp=path.with_suffix('.partial.png'); im.save(temp,'PNG'); os.replace(temp,path)
        atomic_json(path.with_suffix('.json'),{'signature':image_signature(job,shot),'sha256':file_hash(path),'source':'manual import','visible_star_cleanup':cleanup})
        count+=1
    if not count: raise UserError('No matching images found. Filenames must match IMAGE_PROMPTS.txt, for example 001_01.png.')
    job.status('IMAGES_IMPORTED',f'Imported {count} images. Resume to validate and build the draft.')
    return count


def cached_image(job,shot):
    path=job.folder/'images'/f'{shot["id"]}.png'; meta=path.with_suffix('.json')
    if not path.exists() or not meta.exists(): return False
    try:
        data=read_json(meta)
        return data.get('signature')==image_signature(job,shot) and data.get('sha256')==file_hash(path)
    except (OSError,ValueError): return False

def preparation_signature(plan,settings):
    # Choosing/replacing the CapCut template changes only draft construction,
    # not narration or its measured timeline.
    values=vars(settings).copy()
    if not settings.min_shot_seconds:values.pop('min_shot_seconds',None)
    if not settings.sample_script:values.pop('sample_script',None)
    if settings.constant_image_prompt is None:values.pop('constant_image_prompt',None)
    from .remotion_graphics import EDIT_SETTINGS
    for key in ('template_path','sfx_folder')+EDIT_SETTINGS: values.pop(key,None)
    return fingerprint([plan,values])

def preparation_matches(signature,plan,settings):
    if signature==preparation_signature(plan,settings):return True
    # Existing projects used all settings. Accept the old current-template or
    # pre-attachment signature, still matching every narration-related setting.
    values=vars(settings).copy();candidates=[values]
    if settings.constant_image_prompt is None:
        candidates.append({k:v for k,v in values.items() if k!='constant_image_prompt'})
    for candidate in candidates:
        if signature in (fingerprint([plan,candidate]),fingerprint([plan,dict(candidate,template_path='')])):return True
        legacy=candidate.copy()
        if not settings.min_shot_seconds:legacy.pop('min_shot_seconds',None)
        if not settings.sample_script:legacy.pop('sample_script',None)
        if signature in (fingerprint([plan,legacy]),fingerprint([plan,dict(legacy,template_path='')])):return True
    return False

def build_and_install(job,target,cancel,log):
    """User-confirmed build/install; never write the destination after a paused build."""
    from . import capcut
    if job.settings.video_editor!='capcut':raise UserError('Use Open / save Kdenlive project for this editor choice.')
    job.check(cancel)
    draft=job.folder/'capcut'/'draft_content.json'
    if job.data['state'] not in ('READY_FOR_CAPCUT','AWAITING_REVIEW') or not draft.is_file():
        log('Building the complete CapCut draft before installation...')
        run(job,cancel,log)
    job.check(cancel)
    if job.data['state'] not in ('READY_FOR_CAPCUT','AWAITING_REVIEW') or not draft.is_file():
        raise UserError('The destination was not changed. '+job.data.get('message','The draft is not ready yet.'))
    capcut.install(job,target)
    log('Draft installed. Open the destination in CapCut and review it.')


def run(job,cancel,log,key='',plan_only=False,approve_script=False):
    job.require_mutable()
    s=job.settings; s.validate()
    # Remotion dependencies are checked after visual planning, only when a
    # shot actually has overlays to render.
    # Cross-process lock: stale locks require a live-PID check before removal.
    lock=job.folder/'run.lock'
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise UserError('This project has a run.lock. Close other VideoPilot instances; if a previous run crashed, delete run.lock after confirming it is no longer running.')
    os.write(fd,str(os.getpid()).encode()); os.close(fd)
    try:
        def state(code,message): job.status(code,message); log(message); job.check(cancel)
        script=job.folder/'script.json'
        generated=False
        if not script.exists():
            state('WRITING_SCRIPT','Writing and refining the script with Codex…')
            plan=plan_video(s,job.folder/'planner',cancel); atomic_json(script,plan)
            generated=True
            job.data.update(script_origin='codex',script_review_pending=True); job.save()
        else: plan=validate_plan(read_json(script))
        narration='\n\n'.join(x['narration'] for x in plan['scenes'])
        (job.folder/'script.txt').write_text(narration,encoding='utf-8')
        if job.data.get('script_review_pending'):
            if approve_script and not generated and not plan_only:
                job.data['script_review_pending']=False;job.save()
            else:
                state('SCRIPT_READY','Script ready for review in the Script tab. Save any edits, then click Continue project to approve it and generate the voiceover.');return
        cached=preparation_matches(job.data.get('prepared_signature'),plan,s) and all((job.folder/x).is_file() for x in ('timeline.json','audio/narration.wav','captions.srt'))
        if plan_only:
            state('SCRIPT_READY','Script ready. Review it in the Script tab, then click Continue project.'); return
        prepared_hashes=job.data.get('prepared_hashes',{})
        cached=cached and all(prepared_hashes.get(x)==file_hash(job.folder/x) for x in ('timeline.json','audio/narration.wav','captions.srt'))
        if cached:
            timeline=read_json(job.folder/'timeline.json'); write_prompts(job,timeline)
            from .text_layout import reflow_captions
            captions=reflow_captions(timeline['captions'],s.aspect)
            from .text_layout import narration_captions
            scene_files=[job.folder/'audio'/f'{i:03d}.wav' for i in range(1,len(plan['scenes'])+1)]
            if all(p.is_file() for p in scene_files) and sum(round(wav_info(p)['duration']*1e6) for p in scene_files)==timeline['duration']:
                captions=narration_captions(plan,scene_files,s.aspect)
            if captions!=timeline['captions']:
                timeline['captions']=captions;atomic_json(job.folder/'timeline.json',timeline)
                (job.folder/'captions.srt').write_text('\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["start"]+c["duration"])}\n{c["text"]}' for i,c in enumerate(captions,1))+'\n',encoding='utf-8-sig')
                job.data['prepared_hashes']={x:file_hash(job.folder/x) for x in ('timeline.json','audio/narration.wav','captions.srt')}
                log('Refitted subtitles to shorter phrases without regenerating narration or changing shot timing.')
            job.data['prepared_signature']=preparation_signature(plan,s);job.save()
        else:
            # Preserve the requested voice speed. One automatic writing
            # revision is allowed below 60% of target; edited scripts are preserved.
            for revision in range(2):
                state('GENERATING_VOICE','Generating narration locally (two CPU threads)…')
                sig=fingerprint([plan,s.voice,s.speed,s.duration])
                speed=s.speed
                files,durations=synthesize(job,plan,speed,cancel,log)
                actual=sum(durations)
                job.data.update(actual_duration=actual,effective_speed=speed,voice_plan_signature=sig); job.save()
                if actual>=s.duration*.60: break
                feedback=f'Target {s.duration}s; measured narration {actual:.2f}s at {speed:.3f}x. Rewrite the narration to about {s.duration/actual:.3f} times its current length, preserving the story and natural tone. Current script: '+json.dumps(plan,ensure_ascii=False)
                (job.folder/'DURATION_FEEDBACK.txt').write_text(feedback,encoding='utf-8')
                if revision==0 and job.data.get('script_origin')=='codex' and job.data.get('auto_fit_attempts',0)<1:
                    state('REFITTING_SCRIPT','Refining script length using measured narration timing…')
                    job.data['auto_fit_attempts']=1; job.save()
                    corrected=plan_video(s,job.folder/'planner-auto-fit',cancel,feedback)
                    shutil.copy2(script,job.folder/'script-before-auto-fit.json')
                    atomic_json(script,corrected); plan=corrected
                    (job.folder/'script.txt').write_text('\n\n'.join(x['narration'] for x in plan['scenes']),encoding='utf-8')
                    job.data['script_review_pending']=True
                    state('SCRIPT_READY','Script length was revised. Review it in the Script tab, then click Continue project to approve it before generating the revised voiceover.');return
                state('NEEDS_DURATION_EDIT',f'Narration is {actual:.1f}s vs {s.duration}s target. Use Fit script, or edit script.json. Audio was not cut or forced to an unnatural speed.')
                return
            join_wavs(files,job.folder/'audio'/'narration.wav')
            timeline=make_timeline(plan,durations,s); atomic_json(job.folder/'timeline.json',timeline); write_prompts(job,timeline)
            from .text_layout import narration_captions
            timeline['captions']=narration_captions(plan,files,s.aspect)
            atomic_json(job.folder/'timeline.json',timeline)
            if timeline.get('image_hold_exceptions'):
                log(f'Image timing: {len(timeline["image_hold_exceptions"])} shot(s) use a small hold-range exception to preserve narration and visual boundaries. Continuing without regenerating audio or script; details are in timeline.json.')
            captions='\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["start"]+c["duration"])}\n{c["text"]}' for i,c in enumerate(timeline['captions'],1))
            (job.folder/'captions.srt').write_text(captions+'\n',encoding='utf-8-sig')
            job.data['prepared_signature']=preparation_signature(plan,s)
            job.data['prepared_hashes']={x:file_hash(job.folder/x) for x in ('timeline.json','audio/narration.wav','captions.srt')}
            job.save()
        (job.folder/'images').mkdir(exist_ok=True)
        if s.image_mode=='flow':
            from .flow import queue_for, collect_downloads
            queue_for(job,timeline); collected=collect_downloads(job)
            if collected: log(f'Collected {collected} completed Flow image sets.')
        if s.image_mode in ('flow','gemini'):
            from .image_cleanup import upgrade_project_images
            upgrade_project_images(job,timeline,log)
        missing=[shot for shot in timeline['shots'] if not cached_image(job,shot)]
        missing_ids=', '.join(shot['id'] for shot in missing[:8])+(' …' if len(missing)>8 else '')
        existing_missing=[shot['id'] for shot in missing if (job.folder/'images'/f'{shot["id"]}.png').is_file()]
        confirmation_note=(' Existing files need to be imported through Import images manually or confirmed with Use selected: '+', '.join(existing_missing[:8])+'.') if existing_missing else ''
        if missing and s.image_mode=='flow':
            state('WAITING_FOR_FLOW',f'{len(missing)} shot(s) need images: {missing_ids}.'+confirmation_note+' In Flow images, import/select existing images or run the Flow queue for missing ones.'); return
        if missing and s.image_mode=='manual':
            state('WAITING_FOR_IMAGES',f'Images needed for: {missing_ids}.'+confirmation_note+' Use IMAGE_PROMPTS.txt, import the image files, then Continue project.'); return
        if missing:
            if not s.paid_images: raise UserError('Automatic API images require the explicit API billing checkbox, or switch to manual images in a new project.')
            if job.data.get('image_requests',0)+len(missing)>s.max_image_requests:
                raise UserError(f'Image request cap reached: {job.data.get("image_requests",0)} attempted, {len(missing)} still needed, cap {s.max_image_requests}. Raise the project cap explicitly in job.json or import images. This cap is not a currency budget.')
            key=key or get_key()
            if not key: raise UserError('Gemini API key is missing. Enter a session key or save one in Windows Credential Manager.')
            from PIL import Image, ImageOps
            import io
            for index,shot in enumerate(missing,1):
                state('GENERATING_IMAGES',f'Generating image {index}/{len(missing)}; total shots: {len(timeline["shots"])}')
                job.data['image_requests']=job.data.get('image_requests',0)+1; job.save()
                blob=gemini_image(shot['prompt'],s.aspect,s.image_model,key)
                path=job.folder/'images'/f'{shot["id"]}.png'
                with Image.open(io.BytesIO(blob)) as im:
                    from .image_cleanup import clean_visible_star
                    im,cleanup=clean_visible_star(im.convert('RGB'))
                    im=ImageOps.fit(im,s.dimensions,method=Image.Resampling.LANCZOS)
                    temp=path.with_suffix('.partial.png'); im.save(temp,'PNG'); os.replace(temp,path)
                atomic_json(path.with_suffix('.json'),{'signature':image_signature(job,shot),'sha256':file_hash(path),'source':s.image_model,'visible_star_cleanup':cleanup})
        from .image_audit import require_distinct_imports
        require_distinct_imports(job,timeline)
        state('PREPARING_AUDIO','Preparing background audio and sound effects…')
        music=background_path(job.folder,s)
        if s.bgm=='ambient': generated_ambient(music,timeline['duration']/1e6,cancel)
        elif s.bgm=='file':
            info=audio_info(s.bgm_path)
            if info['duration']<=0: raise UserError('Selected music is empty.')
            if Path(s.bgm_path).resolve()!=music.resolve(): shutil.copy2(s.bgm_path,music)
        if s.sfx:
            generated_whoosh(job.folder/'audio'/'whoosh.wav')
            if s.sfx_folder:
                from .sound_library import import_library
                import_library(job,s.sfx_folder,cancel,log)
        if s.video_editor=='capcut' and not s.template_path:
            state('NEEDS_CAPCUT_TEMPLATE','Assets ready. Select your native CapCut sample in Settings, attach it to this project, and Resume.'); return
        template=Template(s.template_path) if s.video_editor=='capcut' else None
        from .editing import prepare_edit
        state('PLANNING_EDIT','Codex is directing the edit from your images and narration...' if s.editing_mode=='codex' else 'Applying gentle preset editing rules...')
        timeline=prepare_edit(job,plan,timeline,cancel,log)
        from .remotion_graphics import render_graphics
        if s.remotion_enabled and s.graphics_percent:state('RENDERING_GRAPHICS','Rendering selected Remotion shots, one at a time…')
        graphics=render_graphics(job,plan,timeline,cancel,log)
        timeline['rendered_clips']=graphics['clips']
        state('BUILDING_DRAFT',f'Building the editable {s.video_editor.title()} project...')
        if s.video_editor=='capcut':
            draft=template.build(timeline,job.folder,s)
            atomic_json(job.folder/'capcut'/'draft_content.json',draft)
        else:
            from .kdenlive import build
            build(job,timeline)
        cleanup_review=[]
        for shot in timeline['shots']:
            meta=read_json(job.folder/'images'/f'{shot["id"]}.json')
            if meta.get('visible_star_cleanup',{}).get('status')=='no_confident_match':
                cleanup_review.append(shot['id'])
        (job.folder/'IMAGE_CLEANUP_REVIEW.txt').write_text(
            'Check these shots for a remaining visible star; detection was uncertain or no star was present.\n'+
            '\n'.join(cleanup_review),encoding='utf-8')
        if cleanup_review: log('Check visible-star cleanup on shots: '+', '.join(cleanup_review)+'. See IMAGE_CLEANUP_REVIEW.txt.')
        atomic_json(job.folder/'validation.json',{'duration_seconds':timeline['duration']/1e6,'target_seconds':s.duration,
            'images':len(timeline['shots']),'max_shot_seconds':max(x['duration'] for x in timeline['shots'])/1e6,
            'all_image_files_verified':all(cached_image(job,x) for x in timeline['shots']),
            'visible_star_review_shots':cleanup_review,
            'image_motion':s.image_motion,'graphics_requested_percent':s.graphics_percent if s.remotion_enabled else 0,
            'graphics_actual_percent':graphics['actual_percent'],'graphics_clips':len(graphics['clips']),
            'template_sha256':file_hash(s.template_path) if template else None,'video_editor':s.video_editor,'editing_mode':s.editing_mode,'capcut_open_verified':False,'rendered':False,
            'notes':['Caption timing is approximate within measured narration beats.','Visual relevance and audio quality need human review.','Legacy CapCut compatibility requires opening the installed draft.']})
        state('READY_FOR_CAPCUT' if template else 'READY_FOR_KDENLIVE',
            'Draft built. Install into a new empty CapCut project and review. Export remains manual.' if template else
            'Kdenlive project ready. Use Open / save Kdenlive project to review the editable timeline and export.')
    except Cancelled as e: job.status('STOPPED',str(e)); log(str(e))
    except Exception as e:
        job.status('ERROR',str(e) if isinstance(e,UserError) else f'{type(e).__name__}: operation failed. Check paths, dependencies and file permissions.')
        raise
    finally:
        lock.unlink(missing_ok=True)
        if job.data['state'] in ('READY_FOR_CAPCUT','READY_FOR_KDENLIVE'):
            from .storage import clean_duplicates,clean_unused_graphics
            try:
                removed=clean_duplicates(job)
                if removed: log(f'Reclaimed {removed/1048576:.2f} MB of verified duplicate Flow downloads.')
                graphics_removed=clean_unused_graphics(job)
                if graphics_removed:log(f'Reclaimed {graphics_removed/1048576:.2f} MB of superseded Remotion clips.')
            except (OSError,ValueError,UserError): log('Duplicate cleanup skipped; project media retained.')


def fit_script(job,cancel,log):
    job.require_mutable()
    feedback=job.folder/'DURATION_FEEDBACK.txt'
    if not feedback.exists(): raise UserError('Run narration first. Fit script uses its measured duration.')
    log('Rewriting the script using measured narration timing…')
    plan=plan_video(job.settings,job.folder/'planner-fit',cancel,feedback.read_text(encoding='utf-8'))
    backup=job.folder/f'script-before-fit-{time.time_ns()}.json'
    shutil.copy2(job.folder/'script.json',backup); atomic_json(job.folder/'script.json',plan)
    (job.folder/'script.txt').write_text('\n\n'.join(scene['narration'] for scene in plan['scenes']),encoding='utf-8')
    job.data['script_review_pending']=True
    job.status('SCRIPT_READY','Script refitted. Review it in the Script tab, then click Continue project.')
