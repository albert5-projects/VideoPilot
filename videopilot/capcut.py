"""Experimental legacy adapter: use native samples, never guess a CapCut schema.
Only a user-selected, empty project may be installed into. Rendering is absent.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json, os, re, shutil, subprocess, time, uuid
from .core import UserError, atomic_json, read_json, file_hash
from .audio import wav_info, audio_info, background_path

def uid(): return str(uuid.uuid4()).upper()
def walk_strings(value):
    if isinstance(value,str): yield value
    elif isinstance(value,list):
        for x in value: yield from walk_strings(x)
    elif isinstance(value,dict):
        for x in value.values(): yield from walk_strings(x)

def replace_ids(value,mapping):
    if isinstance(value,str): return mapping.get(value,value)
    if isinstance(value,list): return [replace_ids(x,mapping) for x in value]
    if isinstance(value,dict): return {k:replace_ids(v,mapping) for k,v in value.items()}
    return value

def load_draft(path):
    path=Path(path)
    if path.is_dir(): path=path/'draft_content.json'
    if path.name!='draft_content.json' or not path.is_file(): raise UserError('Select a native draft_content.json file from your CapCut project.')
    if path.stat().st_size>20*1024*1024: raise UserError('Sample draft is too large. Create a minimal three-track template.')
    try: d=read_json(path)
    except (ValueError,UnicodeError) as e: raise UserError('This draft is encrypted or not JSON. This adapter cannot use it.') from e
    if not isinstance(d,dict) or not isinstance(d.get('tracks'),list) or not isinstance(d.get('materials'),dict):
        raise UserError('Unrecognized CapCut draft structure.')
    return path,d

def parse_text_content(raw):
    """Recognize JSON text or the single styled text run in the 2.1.0 sample."""
    if not isinstance(raw,str):raise UserError('Text content must be a string in the sample draft.')
    try:content=json.loads(raw)
    except ValueError:content=None
    if isinstance(content,dict) and isinstance(content.get('text'),str):
        styles=content.get('styles',[])
        if not isinstance(styles,list) or any(not isinstance(s,dict) for s in styles):
            raise UserError('Text styles are unsupported. Use a single-style plain text sample.')
        if len(styles)>1:raise UserError('Use a single-style plain text sample.')
        return 'json',content
    # The supplied native 2.1.0 draft wraps its text as <...>[words]</...>.
    # Keep every font/style attribute byte-for-byte; reject multiple text runs
    # rather than guessing how a replacement should inherit their formatting.
    match=re.fullmatch(r'(?P<prefix>(?:<[A-Za-z][^<>]*>)+)\[(?P<text>[^<>\[\]]*)\](?P<suffix>(?:</[A-Za-z]+>)+)',raw)
    if match:
        opening=[name.lower() for name in re.findall(r'<([A-Za-z]+)(?=[\s=>])',match['prefix'])]
        closing=[name.lower() for name in re.findall(r'</([A-Za-z]+)>',match['suffix'])]
        if opening and closing==opening[::-1] and set(opening)<= {'outline','b','i','u','size','font','color'}:
            return 'legacy',match.groupdict()
    raise UserError('Text schema is unsupported. Use one plain text clip with a single text style, or supply its draft for adaptation.')

def replace_text_content(raw,text):
    kind,content=parse_text_content(raw)
    if kind=='legacy':
        if any(c in text for c in '<>[]'):
            raise UserError('This CapCut 2.1.0 text format has no verified encoding for < > [ ]. Remove these characters from captions/overlays before continuing.')
        return content['prefix']+'['+text+']'+content['suffix']
    content['text']=text
    units=len(text.encode('utf-16-le'))//2
    for style in content.get('styles',[]):style['range']=[0,units]
    return json.dumps(content,ensure_ascii=False)

class Template:
    def __init__(self,path):
        self.path,self.data=load_draft(path)
        self.index={}
        for category,items in self.data['materials'].items():
            if not isinstance(items,list): raise UserError('Unknown material collection. A custom adapter is needed.')
            for m in items:
                if isinstance(m,dict) and m.get('id'):
                    if m['id'] in self.index: raise UserError('Duplicate material IDs in template.')
                    self.index[m['id']]=(category,m)
        self.samples={}
        # Extra music/SFX tracks need not prevent using a native sample. Select
        # the unique local WAV track as the schema for generated audio tracks.
        audio_candidates=[]
        for track in self.data['tracks']:
            segments=track.get('segments',[])
            if track.get('type')=='audio' and len(segments)==1:
                entry=self.index.get(segments[0].get('material_id'))
                if entry and Path(entry[1].get('path','')).suffix.lower()=='.wav':audio_candidates.append(track)
        if len(audio_candidates)!=1:
            raise UserError('Template needs exactly one local WAV clip on its own audio track. Additional MP3 music/SFX tracks are ignored.')
        audio_sample=audio_candidates[0]
        for track in self.data['tracks']:
            segments=track.get('segments',[])
            if not segments: continue
            kind=track.get('type')
            if kind=='audio' and track is not audio_sample:continue
            if kind not in ('video','audio','text') or kind in self.samples or len(segments)!=1:
                raise UserError('Template must contain exactly one photo, one local WAV and one plain text clip, on separate tracks.')
            seg=segments[0]
            if seg.get('common_keyframes') or seg.get('keyframe_refs'): raise UserError('Remove keyframes/animations from the template.')
            if seg.get('speed',1)!=1: raise UserError('Template clips must use normal speed.')
            if seg.get('material_id') not in self.index: raise UserError('Template material reference is missing.')
            cat,material=self.index[seg['material_id']]
            if kind=='video' and material.get('type') not in ('photo','image'):
                raise UserError('The video track must contain a still photo, not a video.')
            if kind=='audio' and not material.get('path'): raise UserError('Use local WAV audio in the template, not online CapCut music.')
            if kind=='text':
                parse_text_content(material.get('content'))
            self.samples[kind]=(track,seg)
        if set(self.samples)!= {'video','audio','text'}: raise UserError('Template needs one photo track, one audio track and one text track.')
        # Complex template materials can have version-dependent external resource state.
        disallowed=('effects','transitions','animations','stickers')
        for cat in disallowed:
            if self.data['materials'].get(cat):
                raise UserError(f'Remove {cat} from the template. Use plain clips, with no effects or background canvas.')

    def build(self,timeline,job_folder,settings):
        folder=Path(job_folder); draft=deepcopy(self.data)
        draft['id']=uid(); draft['duration']=timeline['duration']; draft['tracks']=[]
        draft['materials']={k:[] for k in self.data['materials']}
        canvas=draft.setdefault('canvas_config',{})
        canvas.update(width=timeline['width'],height=timeline['height'],ratio=settings.aspect)
        draft['fps']=30
        audio_durations={}
        def audio_duration(path):
            key=str(Path(path).resolve())
            if key not in audio_durations:audio_durations[key]=round(audio_info(path)['duration']*1_000_000)
            return audio_durations[key]
        def track_for(kind,name):
            t=deepcopy(self.samples[kind][0]); t.update(id=uid(),segments=[])
            if 'name' in t: t['name']=name
            draft['tracks'].append(t); return t
        def segment(kind,track,start,duration,path=None,text=None,volume=1,top=False,video_info=None):
            sample=deepcopy(self.samples[kind][1]); main=sample['material_id']
            pending=[main]+[s for s in walk_strings(sample) if s in self.index]; used=set()
            while pending:
                old=pending.pop()
                if old in used: continue
                used.add(old)
                pending += [s for s in walk_strings(self.index[old][1]) if s in self.index and s not in used]
            mapping={old:uid() for old in used}; mapping[sample['id']]=uid()
            seg=replace_ids(sample,mapping)
            seg.update(target_timerange={'start':start,'duration':duration},speed=1.0,volume=volume)
            if kind!='text' or seg.get('source_timerange') is not None: seg['source_timerange']={'start':0,'duration':duration}
            seg['common_keyframes']=[]; seg['keyframe_refs']=[]
            if top:
                seg.setdefault('clip',{}).update(transform={'x':0.,'y':.55},scale={'x':1.,'y':1.},rotation=0.)
            elif kind=='text':
                # Keep native subtitle styling but place captions in the lower
                # region reserved by the composed Remotion layouts (center 88%).
                clip=seg.setdefault('clip',{})
                clip.update(transform={'x':0.,'y':-.76},scale={'x':1.,'y':1.},rotation=0.)
            for old in used:
                category,oldmat=self.index[old]; material=replace_ids(deepcopy(oldmat),mapping)
                if old==main:
                    if path:
                        material['path']=str(Path(path).resolve()).replace('\\','/')
                        if 'name' in material: material['name']=Path(path).name
                        if 'material_name' in material: material['material_name']=Path(path).name
                        material['duration']=duration if kind=='video' else audio_duration(path)
                        if kind=='video':
                            material.update(width=timeline['width'],height=timeline['height'],
                                crop={'lower_left_x':0.,'lower_left_y':1.,'lower_right_x':1.,'lower_right_y':1.,
                                      'upper_left_x':0.,'upper_left_y':0.,'upper_right_x':1.,'upper_right_y':0.},crop_ratio='free',crop_scale=1.)
                            if video_info:
                                # Native local video material fields, checked against CapCut drafts.
                                material.update(type='video',has_audio=False,duration=video_info['duration'],picture_from='none')
                    if text is not None:
                        from .text_layout import style_text
                        style_text(material,text,timeline['width'],timeline['height'],emphasis=top)
                        material['text_color']=timeline.get('edit_style',{}).get('emphasis_color' if top else 'caption_color',material['text_color'])
                draft['materials'][category].append(material)
            track['segments'].append(seg)
        visual=track_for('video','Images')
        for index,shot in enumerate(timeline['shots']):
            rendered=timeline.get('rendered_clips',{}).get(shot['id'])
            if rendered and rendered.get('source_shot_id') is not None:
                from .core import file_hash
                if rendered['source_shot_id']!=shot['id'] or rendered.get('source_image_sha256')!=file_hash(folder/'images'/f'{shot["id"]}.png'):
                    raise UserError(f'Rendered graphic for {shot["id"]} uses an outdated or different image. Continue project to rebuild.')
            path=Path(rendered['path']) if rendered else folder/'images'/f'{shot["id"]}.png'
            segment('video',visual,shot['start'],shot['duration'],path,video_info=rendered,volume=0 if rendered else 1)
            seg=visual['segments'][-1]
            clip=seg.setdefault('clip',{})
            clip.update(scale={'x':1.,'y':1.},transform={'x':0.,'y':0.},rotation=0.)
            if rendered or (settings.editing_mode=='rules' and not settings.image_motion):continue
            from .editing import gentle_camera
            camera=shot.get('camera') or gentle_camera(shot,settings,index)
            clip.update(scale={'x':camera[0]['scale'],'y':camera[0]['scale']},transform={'x':camera[0]['x']*2,'y':-camera[0]['y']*2},rotation=0.)
            # Native CapCut 2.1.0 schema, verified against local animated drafts.
            def motion(prop,values,offsets=None):
                return {'id':uid(),'property_type':prop,'keyframe_list':[
                    {'id':uid(),'curveType':'Line','graphID':'',
                     'left_control':{'x':0.,'y':0.},'right_control':{'x':0.,'y':0.},
                     'time_offset':offset,'values':value}
                    for offset,value in zip(offsets or (0,max(1,shot['duration']-33333)),values)]}
            offsets=[round(k['at']*max(1,shot['duration']-33333)) for k in camera]
            seg['common_keyframes']=[motion('KFTypeScale',[[k['scale'],k['scale']] for k in camera],offsets),
                motion('KFTypePositionX',[[k['x']*2] for k in camera],offsets),
                motion('KFTypePositionY',[[-k['y']*2] for k in camera],offsets)]
            if shot.get('transition')=='fade':seg['common_keyframes'].append(motion('KFTypeAlpha',[[0.],[1.]],[0,min(200000,max(1,shot['duration']//3))]))
        effects=[]
        if settings.editing_mode=='codex' and any(s.get('transition')=='woosh' for s in timeline['shots']):
            from .cached_effects import native_transition
            native=native_transition()
            if not native:raise UserError('The selected cached Woosh transition is no longer available. Continue to rebuild the Codex edit plan.')
            if native:
                for index,(left,right) in enumerate(zip(visual['segments'],visual['segments'][1:])):
                    # Occasional accents; do not blur every cut or move narration.
                    if timeline['shots'][index+1].get('transition')!='woosh':continue
                    material=deepcopy(native);material['id']=uid()
                    material['duration']=min(160000,left['target_timerange']['duration']//4,right['target_timerange']['duration']//4)
                    draft['materials'].setdefault('transitions',[]).append(material)
                    left.setdefault('extra_material_refs',[]).append(material['id'])
                    effects.append({'after_shot':timeline['shots'][index]['id'],'name':material['name'],'path':material['path'],'duration':material['duration']})
        atomic_json(folder/'video_effects_report.json',{'native_transitions':effects,'cache_copied':False,
            'motion_style':'Codex keyframes' if settings.editing_mode=='codex' else settings.motion_style if settings.image_motion else 'static'})
        voice=track_for('audio','Narration')
        segment('audio',voice,0,timeline['duration'],folder/'audio'/'narration.wav')
        music=background_path(folder,settings)
        if settings.bgm!='none' and music.exists():
            track=track_for('audio','Background music'); length=audio_duration(music)
            if length<=0: raise UserError('Background music is empty.')
            start=0
            while start<timeline['duration']:
                duration=min(length,timeline['duration']-start)
                segment('audio',track,start,duration,music,volume=timeline.get('edit_style',{}).get('music_gain',.12)); start+=duration
        if settings.sfx:
            track=track_for('audio','Subtle sound effects'); sfx=folder/'audio'/'whoosh.wav'
            length=round(wav_info(sfx)['duration']*1_000_000)
            from .sound_library import select_sound
            for shot in timeline['shots']:
                if shot['sfx']:
                    selected=select_sound(folder,shot) or sfx
                    length=round(wav_info(selected)['duration']*1_000_000)
                    start=shot['start']+shot.get('sfx_offset',0)
                    if start<timeline['duration']:segment('audio',track,start,min(length,timeline['duration']-start),selected,volume=shot.get('sfx_gain',.45))
        if settings.captions:
            track=track_for('text','Captions')
            for c in timeline['captions']: segment('text',track,c['start'],c['duration'],text=c['text'])
        if timeline['overlays']:
            track=track_for('text','Emphasis text')
            for c in timeline['overlays']:
                # Graphic titles already occupy this space; keep subtitles independent.
                if any(shot['id'] in timeline.get('rendered_clips',{}) and shot['start']<c['start']+c['duration'] and c['start']<shot['start']+shot['duration'] for shot in timeline['shots']):continue
                segment('text',track,c['start'],c['duration'],text=c['text'],top=True)
        validate_draft(draft)
        return draft


def validate_draft(draft):
    ids={m['id'] for items in draft['materials'].values() for m in items if isinstance(m,dict) and 'id' in m}
    if not draft['tracks']: raise UserError('Draft has no tracks.')
    for track in draft['tracks']:
        for segment in track['segments']:
            if segment['material_id'] not in ids: raise UserError('Draft has a missing material reference.')
            for ref in segment.get('extra_material_refs',[]):
                if ref not in ids: raise UserError('Draft has a missing extra material reference.')
            t=segment['target_timerange']
            if t['duration']<=0 or t['start']<0 or t['start']+t['duration']>draft['duration']+1:
                raise UserError('Draft has an invalid timeline range.')
    for category in ('videos','audios'):
        for material in draft['materials'].get(category,[]):
            if material.get('path') and not Path(material['path']).is_file(): raise UserError('Draft references a missing asset: '+Path(material['path']).name)


def capcut_running():
    if os.name!='nt': return False
    r=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,errors='replace',
                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
    if r.returncode: raise UserError('Could not check CapCut processes. Close CapCut and retry.')
    return any(line.lower().startswith('"capcut.exe"') for line in r.stdout.splitlines())


def install(job,target):
    if job.data['state'] not in ('READY_FOR_CAPCUT','AWAITING_REVIEW'): raise UserError('The CapCut draft is not ready. Use Continue project to finish preparation before installation.')
    if capcut_running(): raise UserError('Close CapCut completely before installing. Your project will be backed up first.')
    target_path=Path(target)
    if target_path.is_dir(): target_path=target_path/'draft_content.json'
    before=file_hash(target_path)
    path,existing=load_draft(target_path)
    if path.is_symlink(): raise UserError('Use an ordinary project folder, not a symbolic link.')
    if path.resolve()==Path(job.settings.template_path).resolve(): raise UserError('Select a NEW EMPTY destination project, not the template.')
    if any(t.get('segments') for t in existing['tracks']): raise UserError('Destination is not empty. Create a new blank project in CapCut; existing work is never replaced.')
    source=read_json(job.folder/'capcut'/'draft_content.json')
    if source.get('version')!=existing.get('version'): raise UserError('Template and destination draft versions differ. Create both with the same CapCut installation.')
    # Do not pretend this adapter supports the newer mirrored/encrypted project layouts.
    if (path.parent/'draft_info.json').exists(): raise UserError('This project has a draft_info.json mirror. This legacy adapter does not support this layout yet.')
    validate_draft(source)
    backup=job.folder/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]); backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(path,backup/'draft_content.json')
    # Keep the registered destination identity while inheriting native template fields.
    for key in ('id','name','create_time'):
        if key in existing: source[key]=existing[key]
    if capcut_running() or file_hash(path)!=before: raise UserError('Destination changed or CapCut opened. Close it and retry.')
    atomic_json(path,source)
    job.data.update(installed_path=str(path),installed_hash=file_hash(path),backup_path=str(backup/'draft_content.json'))
    job.status('AWAITING_REVIEW','Open the destination in CapCut, check all tracks, then mark finished. No video was rendered.')


def restore(job):
    if capcut_running(): raise UserError('Close CapCut before restoring the backup.')
    target=Path(job.data.get('installed_path','')); backup=Path(job.data.get('backup_path',''))
    if not target.is_file() or not backup.is_file(): raise UserError('No installed project backup is available.')
    # Restore only if no subsequent manual editing would be lost.
    if file_hash(target)!=job.data.get('installed_hash'): raise UserError('CapCut project changed after installation. Restore manually from the backup only after preserving your edits.')
    atomic_json(target,read_json(backup))
    job.data.pop('installed_path',None); job.data.pop('installed_hash',None)
    job.status('READY_FOR_CAPCUT','Blank destination restored from backup.')


def mark_finished(job):
    if job.data['state']!='AWAITING_REVIEW': raise UserError('Install and review the CapCut project before marking it finished.')
    if not Path(job.data.get('installed_path','')).is_file(): raise UserError('Installed project is missing.')
    job.data['reviewed_at']=time.time()
    job.status('FINISHED_UNRENDERED','User confirmed the project is edited and checked in CapCut. Export remains manual.')
