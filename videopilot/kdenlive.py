"""Native Kdenlive 1.1/MLT export, matching the installed editor's structure."""
import math,os,uuid,json
from pathlib import Path
from xml.etree import ElementTree as E
from .core import UserError,atomic_json
from .audio import audio_info,background_path
from .text_layout import fit_text

def prop(node,name,value):E.SubElement(node,'property',name=name).text=str(value)
def frames(us):return round(us*30/1e6)
def ass_time(us):
    cs=round(us/10000);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f'{h}:{m:02}:{s:02}.{cs:02}'

def write_subtitles(path,timeline):
    w,h=timeline['width'],timeline['height'];size=round(min(w*.028,h*.038))
    color=timeline.get('edit_style',{}).get('caption_color','#FFFFFF')[1:]
    color='&H00'+color[4:6]+color[2:4]+color[:2]
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},{color},&H000000FF,&H00172210,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,{round(w*.08)},{round(w*.08)},{round(h*.055)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    rows=[]
    for c in timeline['captions']:
        text,units=fit_text(c['text'],w,h)
        text=text.replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n',r'\N')
        rows.append(f'Dialogue: 0,{ass_time(c["start"])},{ass_time(c["start"]+c["duration"])},Default,,0,0,0,,{{\\fs{round(units*6)}}}'+text)
    path.write_text(header+'\n'.join(rows)+'\n',encoding='utf-8')


def build(job,timeline):
    settings=job.settings;folder=job.folder/'kdenlive';folder.mkdir(exist_ok=True)
    destination=folder/'VideoPilot.kdenlive';w,h=timeline['width'],timeline['height'];total=max(1,frames(timeline['duration']))
    root=E.Element('mlt',{'LC_NUMERIC':'C','producer':'main_bin','root':str(folder.resolve()),'version':'7.41.0'})
    E.SubElement(root,'profile',{'description':'VideoPilot 30 fps','width':str(w),'height':str(h),'frame_rate_num':'30','frame_rate_den':'1','progressive':'1','sample_aspect_num':'1','sample_aspect_den':'1','display_aspect_num':str(w),'display_aspect_den':str(h),'colorspace':'709'})
    black=E.SubElement(root,'producer',id='black',**{'in':'0','out':str(total-1)})
    prop(black,'mlt_service','color');prop(black,'resource','0');prop(black,'length',total)
    bin_entries=[];serial=0;tracks=[]
    def media(path,length,kind,name,gain=1):
        nonlocal serial
        path=Path(path).resolve()
        if not path.is_file():raise UserError('Kdenlive asset missing: '+path.name)
        serial+=1;identifier=f'clip{serial}';clip=E.SubElement(root,'producer',id=identifier,**{'in':'0','out':str(length-1)})
        for k,v in {'resource':str(path),'mlt_service':'qimage' if kind=='image' else 'avformat','length':length,'eof':'pause','kdenlive:id':serial+3,'kdenlive:clipname':name,'kdenlive:proxy':'-'}.items():prop(clip,k,v)
        if kind=='audio':prop(clip,'video_index',-1)
        else:prop(clip,'set.test_audio',1)
        if gain!=1:
            fx=E.SubElement(clip,'filter',{'in':'0','out':str(length-1)})
            prop(fx,'mlt_service','volume');prop(fx,'kdenlive:id','volume');prop(fx,'level',20*math.log10(max(.000001,gain)))
        bin_entries.append((identifier,length));return identifier,clip
    def track(name,audio,entries):
        n=len(tracks);pid=f'playlist{n*2}';playlist=E.SubElement(root,'playlist',id=pid)
        if audio:prop(playlist,'kdenlive:audio_track',1)
        cursor=0
        for start,length,identifier in sorted(entries):
            if start<cursor:raise UserError('Overlapping clips need separate Kdenlive tracks: '+name)
            if start>cursor:E.SubElement(playlist,'blank',length=str(start-cursor))
            E.SubElement(playlist,'entry',producer=identifier,**{'in':'0','out':str(length-1)});cursor=start+length
        second=E.SubElement(root,'playlist',id=f'playlist{n*2+1}')
        if audio:prop(second,'kdenlive:audio_track',1)
        tractor=E.SubElement(root,'tractor',id=f'track{n}',**{'in':'0','out':str(total-1)})
        for k,v in {'kdenlive:track_name':name,'kdenlive:trackheight':72,'kdenlive:timeline_active':1,'kdenlive:collapsed':0}.items():prop(tractor,k,v)
        if audio:prop(tractor,'kdenlive:audio_track',1)
        for source in (pid,second.get('id')):E.SubElement(tractor,'track',producer=source,hide='video' if audio else 'audio')
        tracks.append((tractor.get('id'),audio));return tractor
    voice,_=media(job.folder/'audio/narration.wav',total,'audio','Narration');track('Narration',True,[(0,total,voice)])
    music=background_path(job.folder,settings)
    if settings.bgm!='none' and music.is_file():
        length=max(1,frames(audio_info(music)['duration']*1e6));entries=[]
        identifier,_=media(music,length,'audio','Background music',timeline.get('edit_style',{}).get('music_gain',.12))
        for start in range(0,total,length):entries.append((start,min(length,total-start),identifier))
        track('Music',True,entries)
    if settings.sfx:
        from .sound_library import select_sound
        lanes=[]
        for shot in timeline['shots']:
            if not shot['sfx']:continue
            sound=select_sound(job.folder,shot) or job.folder/'audio/whoosh.wav'
            start=frames(shot['start']+shot.get('sfx_offset',0));length=min(total-start,max(1,frames(audio_info(sound)['duration']*1e6)))
            if length<=0:continue
            identifier,_=media(sound,length,'audio','Sound '+shot['id'],shot.get('sfx_gain',.45))
            lane=next((lane for lane in lanes if lane[-1][0]+lane[-1][1]<=start),None)
            if lane is None:lane=[];lanes.append(lane)
            lane.append((start,length,identifier))
        for i,lane in enumerate(lanes):track(f'Sound effects {i+1}',True,lane)
    visuals=[]
    for shot in timeline['shots']:
        start=frames(shot['start']);length=max(1,frames(shot['start']+shot['duration'])-start)
        rendered=timeline.get('rendered_clips',{}).get(shot['id'])
        identifier,clip=media(rendered['path'] if rendered else job.folder/'images'/f'{shot["id"]}.png',length,'video' if rendered else 'image',shot['id'])
        if not rendered:
            from .editing import gentle_camera
            camera=shot.get('camera') or gentle_camera(shot,settings)
            if any(k['scale']!=1 or k['x'] or k['y'] for k in camera):
                fx=E.SubElement(clip,'filter',{'in':'0','out':str(length-1)})
                values=[]
                for k in camera:
                    x=w*(1-k['scale'])/2+w*k['x'];y=h*(1-k['scale'])/2+h*k['y']
                    values.append(f'{round(k["at"]*(length-1))}={x:.3f} {y:.3f} {w*k["scale"]:.3f} {h*k["scale"]:.3f} 1')
                for key,value in {'mlt_service':'affine','kdenlive:id':'affine','transition.rect':';'.join(values),'transition.distort':0,'transition.valign':'middle','transition.halign':'center','transition.fill':1}.items():prop(fx,key,value)
            if shot.get('transition')=='fade':
                fx=E.SubElement(clip,'filter',{'in':'0','out':str(length-1)})
                prop(fx,'mlt_service','brightness');prop(fx,'kdenlive:id','fadein');prop(fx,'level',f'0=0;{min(6,length-1)}=1');prop(fx,'alpha',1)
        for caption in timeline.get('overlays',[]):
            if rendered:continue
            a=max(start,frames(caption['start']));b=min(start+length,frames(caption['start']+caption['duration']))
            if b<=a:continue
            text,size=fit_text(caption['text'],w,h,emphasis=True)
            fx=E.SubElement(clip,'filter',{'in':str(a-start),'out':str(b-start-1)})
            for key,value in {'mlt_service':'dynamictext','kdenlive:id':'dynamictext','argument':text.replace('#',r'\#'),'geometry':f'{w*.08} {h*.12} {w*.84} {h*.2}','family':'Arial','size':round(size*6),'weight':800,'fgcolour':timeline.get('edit_style',{}).get('emphasis_color','#FFD166'),'bgcolour':'#00000000','outlinecolour':'#FF101722','outlinewidth':2,'halign':'center','valign':'middle'}.items():prop(fx,key,value)
        visuals.append((start,length,identifier))
    track('Images and Remotion',False,visuals)
    sequence_id='{'+str(uuid.uuid4())+'}'
    sequence=E.SubElement(root,'tractor',id='sequence',**{'in':'0','out':str(total-1)})
    for key,value in {'kdenlive:uuid':sequence_id,'kdenlive:control_uuid':sequence_id,'kdenlive:id':3,'kdenlive:producer_type':17,'kdenlive:clipname':'VideoPilot','kdenlive:duration':total,'kdenlive:maxduration':total,'kdenlive:sequenceproperties.tracksCount':len(tracks),'kdenlive:sequenceproperties.tracks':len(tracks),'kdenlive:sequenceproperties.zoneout':total,'kdenlive:sequenceproperties.hasAudio':1,'kdenlive:sequenceproperties.hasVideo':1,'kdenlive:sequenceproperties.activeTrack':len(tracks)-1,'kdenlive:sequenceproperties.groups':'[]'}.items():prop(sequence,key,value)
    E.SubElement(sequence,'track',producer='black')
    for i,(identifier,audio) in enumerate(tracks,1):
        E.SubElement(sequence,'track',producer=identifier)
        transition=E.SubElement(sequence,'transition',{'in':'0','out':str(total-1)})
        for key,value in {'mlt_service':'mix' if audio else 'qtblend','a_track':0,'b_track':i,'internal_added':237,'always_active':1,'sum':1}.items():prop(transition,key,value)
    if settings.captions:
        subtitle=destination.with_suffix('.kdenlive.ass');write_subtitles(subtitle,timeline)
        prop(sequence,'kdenlive:sequenceproperties.subtitlesList',json.dumps([{'id':0,'name':'Subtitles','file':str(subtitle.resolve())}]))
        fx=E.SubElement(sequence,'filter',{'in':'0','out':str(total-1)})
        prop(fx,'mlt_service','avfilter.subtitles');prop(fx,'internal_added',237);prop(fx,'av.filename',str(subtitle.resolve()))
    main=E.SubElement(root,'playlist',id='main_bin')
    for key,value in {'xml_retain':1,'kdenlive:docproperties.version':'1.1','kdenlive:docproperties.documentid':str(uuid.uuid4().int)[:13],'kdenlive:docproperties.uuid':sequence_id,'kdenlive:docproperties.activetimeline':sequence_id,'kdenlive:docproperties.opensequences':sequence_id,'kdenlive:docproperties.audioChannels':2,'kdenlive:docproperties.enableproxy':0}.items():prop(main,key,value)
    for identifier,length in bin_entries+[('sequence',total)]:E.SubElement(main,'entry',producer=identifier,**{'in':'0','out':str(length-1)})
    wrapper=E.SubElement(root,'tractor',id='project',**{'in':'0','out':str(total-1)})
    prop(wrapper,'kdenlive:projectTractor',1);E.SubElement(wrapper,'track',producer='sequence',**{'in':'0','out':str(total-1)})
    E.indent(root);temp=destination.with_suffix('.partial');E.ElementTree(root).write(temp,encoding='utf-8',xml_declaration=True)
    validate(temp);os.replace(temp,destination)
    atomic_json(folder/'export_report.json',{'project':str(destination),'frames':total,'tracks':len(tracks),'editor_open_verified':False})
    return destination

def validate(path):
    root=E.parse(path).getroot();ids={e.get('id') for e in root if e.get('id')}
    if len(ids)!=len([e for e in root if e.get('id')]):raise UserError('Duplicate Kdenlive identifiers.')
    for e in root.iter():
        if e.tag in ('entry','track') and e.get('producer') not in ids:raise UserError('Missing Kdenlive producer reference.')
        if e.tag=='entry' and int(e.get('out','0'))<int(e.get('in','0')):raise UserError('Invalid Kdenlive clip range.')
        if e.tag=='property' and e.get('name') in ('resource','av.filename') and e.text!='0' and not Path(e.text or '').is_file():raise UserError('Missing Kdenlive media file.')
    return root
