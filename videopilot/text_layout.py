"""Conservative two-line fitting using the native sample's own font."""
import re,json
from PIL import ImageFont


def speech_captions(text,start,duration,aspect,audio_path=None):
    """Phrase timing within a measured scene; optionally exclude silent audio frames."""
    from .core import split_caption
    phrases=split_caption(text,max_chars=24 if aspect=='9:16' else 36)
    weights=[max(1,len(re.sub(r'\W','',phrase))) for phrase in phrases]
    total=sum(weights);used=0;activity=None
    if audio_path is not None:
        import wave
        import numpy as np
        with wave.open(str(audio_path),'rb') as audio:
            if audio.getsampwidth()==2:
                rate=audio.getframerate();channels=audio.getnchannels()
                samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').reshape(-1,channels)
                hop=max(1,round(rate*.01));usable=len(samples)//hop*hop
                if usable:
                    levels=np.max(np.abs(samples[:usable].astype(np.int32)).reshape(-1,hop*channels),axis=1)
                    activity=np.flatnonzero(levels>105)*hop/rate
                    if not len(activity):activity=None
    boundaries=[start]
    for weight in weights[:-1]:
        used+=weight;fraction=used/total
        offset=duration*fraction
        if activity is not None:
            offset=float(activity[min(len(activity)-1,round(fraction*(len(activity)-1)))])*1e6
        remaining=len(phrases)-len(boundaries)
        boundaries.append(max(boundaries[-1]+1,min(start+duration-remaining,start+round(offset))))
    boundaries.append(start+duration)
    return [{'text':phrase,'start':a,'duration':b-a} for phrase,a,b in zip(phrases,boundaries,boundaries[1:]) if b>a]


def narration_captions(plan,files,aspect):
    from .audio import wav_info
    result=[];cursor=0
    for scene,path in zip(plan['scenes'],files):
        duration=round(wav_info(path)['duration']*1e6)
        result.extend(speech_captions(scene['narration'],cursor,duration,aspect,path))
        cursor+=duration
    return result


def reflow_captions(captions,aspect):
    from .core import split_caption
    result=[]
    for caption in captions:
        phrases=split_caption(caption['text'],max_chars=24 if aspect=='9:16' else 36)
        total=sum(len(p.split()) for p in phrases);used=0
        for phrase in phrases:
            start=caption['start']+round(caption['duration']*used/total)
            used+=len(phrase.split());end=caption['start']+round(caption['duration']*used/total)
            result.append({**caption,'text':phrase,'start':start,'duration':end-start})
    return result


def fit_text(text,width,height,font_path='',emphasis=False):
    # CapCut 2.1 native font units are much smaller than output pixel units.
    # Fit conservatively at six pixels per unit and keep 12% side margins.
    pixels=min(width*.047,height*.065)*1.12 if emphasis else min(width*.028,height*.038)
    try:font=ImageFont.truetype(font_path,max(1,round(pixels)))
    except (OSError,ValueError):font=ImageFont.load_default(size=max(1,round(pixels)))
    def measure(s):return font.getlength(s)
    limit=width*.76;words=text.split();lines=[];line=''
    for word in words:
        candidate=(line+' '+word).strip()
        if line and measure(candidate)>limit:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    # Keep all content, shrinking a long token or an unusual long emphasis title.
    scale=min(1,limit/max(1,max((measure(s) for s in lines),default=1)),2/max(1,len(lines)),
              height*.115/max(1,len(lines)*pixels*1.3))
    return '\n'.join(lines),round(pixels*scale/6,3)


def style_text(material,text,width,height,emphasis=False):
    from .capcut import replace_text_content,parse_text_content
    fitted,size=fit_text(text,width,height,material.get('font_path',''),emphasis)
    raw=replace_text_content(material['content'],fitted)
    kind,content=parse_text_content(raw)
    if kind=='legacy':raw=re.sub(r'<size=[^>]+>',f'<size={size}>',raw)
    else:
        for style in content.get('styles',[]):
            if 'size' in style:style['size']=size
        raw=json.dumps(content,ensure_ascii=False)
    material['content']=raw
    if 'text' in material:material['text']=fitted
    material.update(font_size=size,text_size=round(size*2),text_color='#FFD166' if emphasis else '#FFFFFF',
        border_color='#101722',border_width=.06,alignment=1,letter_spacing=.02 if emphasis else 0.,
        italic_degree=10 if emphasis else 0,bold_width=.012 if emphasis else .008)
    if not emphasis:
        material['force_apply_line_max_width']=False
