"""Optional, sequential Remotion shot rendering using an existing installation."""
import math, os, shutil, subprocess, tempfile, time
from pathlib import Path
from .core import ROOT, UserError, Cancelled, read_json, atomic_json, fingerprint, file_hash

ASSETS=ROOT/'videopilot'/'remotion_assets'
EDIT_SETTINGS=('image_motion','editing_mode','video_editor','motion_style','kdenlive_path','remotion_enabled','graphics_percent','graphics_theme','graphics_accent','remotion_path')


def select_shots(timeline,percent):
    """Dither by cumulative runtime, rounding coverage to whole shots."""
    if percent<=0:return []
    if percent>=100:return list(timeline['shots'])
    selected=[]; covered=0; elapsed=0
    for shot in timeline['shots']:
        elapsed+=shot['duration']; wanted=elapsed*percent/100
        if abs(covered+shot['duration']-wanted)<=abs(covered-wanted):
            selected.append(shot);covered+=shot['duration']
    # Improve the final rounding error without changing the shot boundaries.
    target=timeline['duration']*percent/100
    for shot in timeline['shots']:
        if shot not in selected and abs(covered+shot['duration']-target)<abs(covered-target):
            selected.append(shot);covered+=shot['duration']
    return sorted(selected,key=lambda s:s['start'])


def graphic_for(plan,shot):
    if shot.get('graphic_override'):return shot['graphic_override']
    scene=plan['scenes'][shot['scene']-1];graphic=scene.get('graphic')
    if graphic and graphic.get('kind')!='none' and graphic.get('title','').strip():
        result=dict(graphic)
    else:
        result={'kind':'focus','title':scene['overlay'] or ' '.join(scene['narration'].split()[:8])[:80],'items':[]}
    # Existing scripts remain usable without inventing new facts.
    result['kind']={'title':'focus','steps':'process'}.get(result['kind'],result['kind'])
    if not result.get('icons'):
        topics={'light':'lamp light bulb illuminate','clock':'time hour minute wait','water':'water liquid pour rain ocean',
            'fire':'fire heat oven bake hot','leaf':'leaf leaves plant grow tree','bread':'bread dough flour loaf bakery',
            'person':'person people family human','globe':'earth world planet country','book':'book learn study history',
            'shield':'safe protect defense','heart':'heart love care','gear':'machine engine tool work',
            'brain':'brain think mind memory','network':'connect network internet','coin':'money coin cost price',
            'house':'house home shelter','mountain':'mountain rock hill','moon':'night dark sleep','sun':'sun morning dawn sunrise','door':'door enter open unlock'}
        import re
        def icon(text):
            words=set(re.findall(r'[a-z]+',text.lower()))
            matches=[(len(words&set(keys.split())),key) for key,keys in topics.items()]
            score,name=max(matches)
            return name if score else 'spark'
        context=scene.get('visual','')+' '+scene['narration']
        if result['kind'] in ('focus','orbit'):
            result['icons']=[icon(result['title']+' '+context)]+[icon(item) for item in result['items']]
        else:result['icons']=[icon(item) for item in result['items']] or [icon(context)]
    return result


def graphic_timing(plan,shot,timeline,graphic):
    """Approximate spoken cue positions within measured scene audio, not forced alignment."""
    import re
    words=re.findall(r"[a-z0-9]+",plan['scenes'][shot['scene']-1]['narration'].lower())
    scene_shots=[s for s in timeline['shots'] if s['scene']==shot['scene']]
    start=min(s['start'] for s in scene_shots);duration=sum(s['duration'] for s in scene_shots)
    stop={'the','a','an','and','or','to','in','of','on','is','it','for','with','from'}
    cues=[]
    for i,item in enumerate(graphic.get('items',[])):
        tokens=set(re.findall(r'[a-z0-9]+',item.lower()))-stop
        matches=[j for j,word in enumerate(words) if word in tokens]
        if matches:offset=start+duration*min(matches)/max(1,len(words))-shot['start']
        else:offset=shot['duration']*i/max(1,len(graphic['items']))*.65
        cues.append(round(max(0,min(max(0,shot['duration']-350000),offset))*30/1e6))
    if graphic['kind'] in ('focus','orbit'):cues.insert(0,0)
    return cues or [0]


def runtime(settings):
    root=Path(settings.remotion_path).expanduser().resolve();modules=root/'node_modules'
    versions=[]
    for package in ('remotion','@remotion/bundler','@remotion/renderer'):
        path=modules/package/'package.json'
        if not path.is_file():raise UserError('Remotion is incomplete. Select the existing project containing node_modules in Customize graphics.')
        versions.append(read_json(path)['version'])
    if len(set(versions))!=1 or not versions[0].startswith('4.'):
        raise UserError('Use matching Remotion 4.x renderer, bundler and remotion packages.')
    node=shutil.which('node')
    if not node:raise UserError('Node.js is required for Remotion. Restart VideoPilot after installing Node.js.')
    browsers=list((modules/'.remotion'/'chrome-headless-shell').glob('**/chrome-headless-shell.exe'))
    if browsers:browser=str(browsers[0])
    else:
        from .flow_browser import browser_executable
        browser=str(browser_executable())
    return {'root':str(root),'node':node,'browser':browser,'version':versions[0]}


def probe_video(path,shot,width,height):
    probe=shutil.which('ffprobe')
    if not probe:raise UserError('FFprobe is required to verify Remotion clips. Install FFmpeg and restart VideoPilot.')
    result=subprocess.run([probe,'-v','error','-select_streams','v:0','-show_entries',
        'stream=width,height,duration,codec_name','-of','json',str(path)],capture_output=True,text=True,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        stream=__import__('json').loads(result.stdout)['streams'][0]
        duration=round(float(stream['duration'])*1e6)
        if result.returncode or stream['codec_name']!='h264' or (stream['width'],stream['height'])!=(width,height) or duration+1000<shot['duration']:
            raise ValueError('Unexpected rendered video format')
        return duration
    except (ValueError,KeyError,IndexError):raise UserError('Remotion output failed video validation: '+Path(path).name) from None


def render_graphics(job,plan,timeline,cancel,log,*,selected_shots=None,planned_overlays=None):
    job.require_mutable();s=job.settings
    selected=(select_shots(timeline,s.graphics_percent) if s.remotion_enabled else []) if selected_shots is None else selected_shots
    from .overlay_planner import plan_overlay
    overlays={};skipped={};accepted=[]
    for shot in selected:
        job.check(cancel)
        if planned_overlays is None:overlay=plan_overlay(job,plan,shot,cancel,log)
        else:
            from .overlay_planner import validate_overlay
            overlay=validate_overlay(planned_overlays[shot['id']],shot['duration']/1e6)
        if overlay['elements']:
            overlays[shot['id']]=overlay;accepted.append(shot)
        else:
            skipped[shot['id']]=overlay.get('reason','No useful overlay.')
            log(f'Shot {shot["id"]}: no useful overlay; using the original image without Remotion rendering.')
            if len(skipped)>5:
                log('Remotion skipped for this video: more than five overlay plans produced no useful overlay. Continuing with the original images.')
                accepted.clear()
                break
    selected=accepted
    actual=sum(x['duration'] for x in selected)/timeline['duration']*100
    report={'enabled':s.remotion_enabled,'requested_percent':s.graphics_percent,'actual_percent':round(actual,2),'clips':{},'skipped':skipped}
    if not selected:
        atomic_json(job.folder/'graphics_report.json',report);return report
    env=runtime(s)
    if not shutil.which('ffprobe'):raise UserError('FFprobe is required for Remotion output verification.')
    folder=job.folder/'graphics';folder.mkdir(exist_ok=True)
    engine=fingerprint([file_hash(p) for p in sorted(ASSETS.iterdir()) if p.suffix in ('.jsx','.cjs')])
    pending=[]
    for shot in selected:
        job.check(cancel)
        image=job.folder/'images'/f'{shot["id"]}.png'
        props={'width':timeline['width'],'height':timeline['height'],'frames':max(1,math.ceil(shot['duration']*30/1e6)),
            'graphic':graphic_for(plan,shot),'imageMotion':s.editing_mode=='codex' or s.image_motion,'theme':s.graphics_theme,'accent':s.graphics_accent,
            'camera':shot.get('camera'),'transition':shot.get('transition','cut')}
        props.update(scene=shot['scene'],cueFrames=shot.get('cue_frames',graphic_timing(plan,shot,timeline,props['graphic'])))
        props['overlayPlan']=overlays[shot['id']]
        source_hash=file_hash(image)
        sig=fingerprint([engine,env['version'],props,source_hash])
        # Content-addressed files keep an interrupted rebuild from breaking an older draft.
        path=folder/f'{shot["id"]}-{sig[:16]}.mp4';meta=path.with_suffix('.json')
        valid=False
        if path.is_file() and meta.is_file():
            try:
                record=read_json(meta)
                valid=record.get('signature')==sig and record.get('sha256')==file_hash(path)
            except (OSError,ValueError):pass
        item={'id':shot['id'],'image':str(image),'props':props,'output':str(path),'signature':sig,'shot':shot,'source_image_sha256':source_hash}
        if valid:
            duration=probe_video(path,shot,timeline['width'],timeline['height'])
            report['clips'][shot['id']]={'path':str(path),'duration':duration,'graphic':props['graphic'],'source_shot_id':shot['id'],'source_image_sha256':source_hash}
        else:pending.append(item)
    log(f'Remotion: {len(selected)} shots, {actual:.1f}% of runtime; {len(pending)} need rendering.')
    if pending:
        with tempfile.TemporaryDirectory(prefix='remotion-',dir=folder) as tmp:
            work=Path(tmp);request=work/'request.json';progress=work/'progress.json';stop=work/'cancel'
            atomic_json(request,dict(env,entry=str(ASSETS/'index.jsx'),work=str(work),progress=str(progress),cancel=str(stop),items=pending))
            proc_env=os.environ.copy();proc_env.update(OMP_NUM_THREADS='2',REMOTION_TELEMETRY_DISABLED='1')
            logpath=work/'renderer.log'
            with logpath.open('w',encoding='utf-8') as output:
                p=subprocess.Popen([env['node'],'--max-old-space-size=1024',str(ASSETS/'render.cjs'),str(request)],
                    cwd=ROOT,env=proc_env,stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                started=time.monotonic();last=''
                try:
                    while p.poll() is None:
                        if cancel.wait(.3):raise Cancelled('Remotion stopped. Completed clips can be reused on resume.')
                        if time.monotonic()-started>max(300,len(pending)*180):raise UserError('Remotion timed out. Try fewer graphics or close other heavy apps.')
                        if progress.exists():
                            try:
                                message=read_json(progress).get('message','')
                                if message!=last:log(message);last=message
                            except (OSError,ValueError):pass
                    if p.returncode:
                        detail=logpath.read_text(encoding='utf-8',errors='replace')[-1800:]
                        raise UserError('Remotion rendering failed. '+detail)
                finally:
                    if p.poll() is None:
                        stop.touch()
                        try:p.wait(10)
                        except subprocess.TimeoutExpired:
                            if os.name=='nt':subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                            else:p.kill()
                            p.wait(timeout=10)
                    # Promote only fully rendered and verified clips, including ones
                    # completed before cancellation. A partial MP4 is never cached.
                    for item in pending:
                        path=Path(item['output']);ready=path.with_suffix('.ready.mp4')
                        if not ready.exists():continue
                        duration=probe_video(ready,item['shot'],timeline['width'],timeline['height'])
                        os.replace(ready,path)
                        atomic_json(path.with_suffix('.json'),{'signature':item['signature'],'sha256':file_hash(path)})
                        report['clips'][item['id']]={'path':str(path),'duration':duration,'graphic':item['props']['graphic'],'source_shot_id':item['id'],'source_image_sha256':item['source_image_sha256']}
    atomic_json(job.folder/'graphics_report.json',report)
    return report
