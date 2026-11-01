"""Local state, validated inputs and atomic writes. No network or shell execution."""
from __future__ import annotations
import hashlib, json, math, os, re, time, uuid
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'VideoPilot'

class UserError(Exception): pass
class Paused(UserError): pass
class Cancelled(UserError): pass

def atomic_json(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

@dataclass
class Settings:
    idea: str = ''
    details: str = ''
    sample_script: str = ''
    # None preserves prompts in projects created before this field existed.
    constant_image_prompt: str | None = None
    style: str = 'Cinematic documentary'
    tone: str = 'Calm, curious storyteller'
    audience: str = 'General YouTube audience'
    duration: int = 60
    aspect: str = '9:16'
    shot_seconds: float = 5.0
    min_shot_seconds: float = 0.0
    image_motion: bool = True
    editing_mode: str = 'rules'
    video_editor: str = 'capcut'
    motion_style: str = 'slow_zoom'
    kdenlive_path: str = str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Kdenlive/bin/kdenlive.exe')
    remotion_enabled: bool = False
    graphics_percent: int = 25
    graphics_theme: str = 'Editorial'
    graphics_accent: str = '#84e1cc'
    remotion_path: str = str(Path.home()/'vs code projects'/'mindistry_yt')
    voice: str = 'am_michael'
    language: str = 'en-us'
    speed: float = 1.0
    codex_model: str = ''
    image_mode: str = 'flow'
    image_model: str = 'gemini-2.5-flash-image'
    max_image_requests: int = 30
    paid_images: bool = False
    bgm: str = 'ambient'
    bgm_path: str = ''
    sfx: bool = True
    sfx_folder: str = ''
    captions: bool = True
    template_path: str = ''
    capcut_version: str = '2.1.0'
    flow_outputs: int = 1
    flow_downloads: str = ''
    def validate(self):
        if self.constant_image_prompt is not None and (not isinstance(self.constant_image_prompt,str) or len(self.constant_image_prompt)>12000):
            raise UserError('Constant image prompt must be text of at most 12,000 characters.')
        if not self.idea.strip(): raise UserError('Enter a video idea.')
        if not isinstance(self.style,str) or not self.style.strip() or len(self.style)>2000: raise UserError('Describe your image style in 1-2000 characters.')
        if type(self.image_motion) is not bool or type(self.remotion_enabled) is not bool: raise UserError('Choose whether image movement and Remotion are enabled.')
        if self.editing_mode not in ('rules','codex'):raise UserError('Choose preset rules or Codex-directed editing.')
        if self.video_editor not in ('capcut','kdenlive'):raise UserError('Choose CapCut or Kdenlive.')
        if self.motion_style not in ('slow_zoom','pan','float','mixed'):raise UserError('Choose slow zoom, pan, float or mixed movement.')
        if type(self.graphics_percent) is not int or not 0<=self.graphics_percent<=100: raise UserError('Graphics coverage must be a whole percentage from 0 to 100.')
        if self.graphics_theme not in ('Editorial','Minimal','Bold'): raise UserError('Choose an Editorial, Minimal or Bold graphics theme.')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',self.graphics_accent): raise UserError('Use a six-digit graphics color, such as #84e1cc.')
        if len(self.idea)+len(self.details)>40000: raise UserError('Brief is too long (40,000 characters max).')
        if not 15 <= self.duration <= 1800: raise UserError('Duration must be 15–1800 seconds.')
        if self.aspect not in ('9:16','16:9','1:1'): raise UserError('Choose 9:16, 16:9 or 1:1.')
        if not math.isfinite(self.shot_seconds) or not .5 <= self.shot_seconds <= 120: raise UserError('Maximum image hold must be 0.5–120 seconds; decimals are allowed.')
        if not math.isfinite(self.min_shot_seconds) or not (self.min_shot_seconds==0 or .5<=self.min_shot_seconds<=self.shot_seconds):
            raise UserError('Minimum image hold must be 0 (off), or at least 0.5 seconds and no greater than the maximum.')
        if not .8 <= self.speed <= 1.2: raise UserError('Voice speed must be 0.8–1.2.')
        if self.language not in ('en-us','en-gb'): raise UserError('This build supports English narration (US/UK).')
        if not re.fullmatch(r'(?:[a-z]{2}_[a-z0-9_]+|nano_[a-f0-9]{32})', self.voice): raise UserError('Invalid narrator voice ID.')
        if self.image_mode not in ('flow','manual','gemini'): raise UserError('Unknown image provider.')
        if not 1<=self.max_image_requests<=1000: raise UserError('Image request limit must be 1–1000.')
        if not re.fullmatch(r'[A-Za-z0-9._-]+', self.image_model): raise UserError('Invalid image model ID.')
        if self.flow_outputs not in (1,2,3,4): raise UserError('Flow outputs per prompt must be 1–4.')
        if self.bgm not in ('ambient','file','none'): raise UserError('Invalid music mode.')
        if self.bgm=='file' and (not Path(self.bgm_path).is_file() or Path(self.bgm_path).suffix.lower() not in ('.mp3','.wav')): raise UserError('Select an MP3 or PCM WAV music file.')
    @property
    def dimensions(self):
        return {'9:16':(1080,1920),'16:9':(1920,1080),'1:1':(1080,1080)}[self.aspect]

class Job:
    def __init__(self, folder):
        self.folder=Path(folder).resolve(); self.path=self.folder/'job.json'
        self.data=read_json(self.path)
        self.settings=Settings(**self.data['settings'])
    @classmethod
    def create(cls, settings, root=None):
        settings.validate()
        slug=re.sub(r'[^a-zA-Z0-9_-]+','-',settings.idea[:36]).strip('-') or 'video'
        folder=Path(root or DATA/'projects')/(time.strftime('%Y%m%d-%H%M%S')+'-'+slug+'-'+uuid.uuid4().hex[:6])
        from .cloned_voices import is_nano,reference,worker_python
        if is_nano(settings.voice):
            worker_python(settings.voice)
            reference(settings.voice)
        folder.mkdir(parents=True)
        if is_nano(settings.voice):reference(settings.voice,folder)
        atomic_json(folder/'job.json',{'version':1,'settings':asdict(settings),'state':'NEW','message':'Ready','image_requests':0})
        return cls(folder)
    def status(self,state,message):
        self.data.update(state=state,message=message,updated=time.time()); self.save()
    def save(self): atomic_json(self.path,self.data)
    def require_mutable(self):
        if self.data.get("installed_path"):
            raise UserError("This project has been handed to an editor. Create an editing revision to avoid changing media used by that edit.")
    def check(self,cancel):
        if cancel.is_set(): raise Cancelled('Stopped. Completed assets are saved; Resume continues safely.')

GRAPHIC_KINDS=['none','focus','process','cycle','comparison','timeline','orbit','title','steps']
GRAPHIC_ICONS=['light','clock','water','fire','leaf','bread','person','globe','book','shield','heart','gear','spark','brain','network','coin','house','mountain','moon','sun','door']
GRAPHIC_SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'kind':{'type':'string','enum':GRAPHIC_KINDS},
    'title':{'type':'string'},'items':{'type':'array','items':{'type':'string'}},
    'icons':{'type':'array','items':{'type':'string','enum':GRAPHIC_ICONS}}},'required':['kind','title','items','icons']}
SCENE_SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'narration':{'type':'string'},'visual':{'type':'string'},'overlay':{'type':'string'},
    'sfx':{'type':'boolean'},'sfx_query':{'type':'string'},'graphic':GRAPHIC_SCHEMA},'required':['narration','visual','overlay','sfx','sfx_query','graphic']}
PLAN_SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'title':{'type':'string'},'visual_bible':{'type':'string'},
    'fact_check_notes':{'type':'array','items':{'type':'string'}},
    'scenes':{'type':'array','items':SCENE_SCHEMA}},
    'required':['title','visual_bible','fact_check_notes','scenes']}

def validate_plan(plan):
    if not isinstance(plan,dict) or not isinstance(plan.get('scenes'),list): raise UserError('Script must contain a scenes array.')
    if not 1<=len(plan['scenes'])<=1000: raise UserError('Script requires 1–1000 scenes.')
    for field in ('title','visual_bible'):
        if not isinstance(plan.get(field),str) or not plan[field].strip(): raise UserError('Script is missing '+field)
    for i,s in enumerate(plan['scenes'],1):
        for key in ('narration','visual','overlay'):
            if not isinstance(s.get(key),str): raise UserError(f'Scene {i}: invalid {key}.')
        if not s['narration'].strip(): raise UserError(f'Scene {i}: narration is empty. Add a spoken beat or remove this unused scene.')
        if len(s['narration'])>600: raise UserError(f'Scene {i}: narration has {len(s["narration"])} characters; split it into shorter scenes of at most 600 characters each.')
        if not s['visual'].strip(): raise UserError(f'Scene {i}: visual prompt is empty.')
        if len(s['overlay'])>70: raise UserError(f'Scene {i}: overlay must be at most 70 characters.')
        if type(s.get('sfx')) is not bool: raise UserError(f'Scene {i}: sfx must be true/false.')
        if not isinstance(s.get('sfx_query',''),str) or len(s.get('sfx_query',''))>120: raise UserError(f'Scene {i}: use a short sound-effect search phrase.')
        g=s.get('graphic')
        if g is not None:
            if not isinstance(g,dict) or g.get('kind') not in GRAPHIC_KINDS: raise UserError(f'Scene {i}: invalid graphic type.')
            if not isinstance(g.get('title'),str) or len(g['title'])>80: raise UserError(f'Scene {i}: graphic title must be at most 80 characters.')
            if not isinstance(g.get('items'),list) or len(g['items'])>3 or any(not isinstance(x,str) or len(x)>80 for x in g['items']): raise UserError(f'Scene {i}: use at most three short graphic items.')
            if g['kind']=='comparison' and len(g['items'])!=2: raise UserError(f'Scene {i}: comparison graphics require two items.')
            if not isinstance(g.get('icons',[]),list) or len(g.get('icons',[]))>4 or any(x not in GRAPHIC_ICONS for x in g.get('icons',[])):raise UserError(f'Scene {i}: choose up to four supported graphic icons.')
    return plan

def split_caption(text, max_words=5, max_chars=28):
    # Performance cues belong to the TTS input, never the displayed transcript.
    # Match known cues only; ordinary bracketed content is not discarded.
    text=re.sub(r'\[(?:sighs?|laugh(?:s|ing|ter)?|chuckles?|cough(?:s|ing)?|gasps?|sniff(?:s|le|les|ling)?|groans?|shush|clear throat|clears throat|throat clearing|yawns?|giggles?)\]',
                '',text,flags=re.IGNORECASE)
    phrases=[];current=[]
    for word in text.split():
        if current and (len(current)>=max_words or len(' '.join(current+[word]))>max_chars):
            phrases.append(' '.join(current));current=[]
        current.append(word)
        if re.search(r'[.!?…。！？][\"\'”’»\)\]]*$',word):
            phrases.append(' '.join(current));current=[]
    if current:phrases.append(' '.join(current))
    return phrases

def make_timeline(plan, durations, settings):
    if len(plan['scenes'])!=len(durations): raise UserError('Narration/scene count mismatch.')
    shots=[]; captions=[]; overlays=[]; cursor=0
    for idx,(scene,seconds) in enumerate(zip(plan['scenes'],durations),1):
        duration=round(seconds*1_000_000)
        if duration<=0: raise UserError('Empty narration audio.')
        count=max(1,math.ceil(duration/(settings.shot_seconds*1_000_000)))
        if settings.min_shot_seconds and duration//count<math.ceil(settings.min_shot_seconds*1_000_000):
            minimum=settings.min_shot_seconds*1_000_000;maximum=settings.shot_seconds*1_000_000
            # Minimize total time outside the preferred range; ties favor fewer
            # cuts. Never change the recorded narration to satisfy image timing.
            candidates={count,max(1,math.floor(duration/minimum))}
            count=min(candidates,key=lambda n:(max(0,n*minimum-duration,duration-n*maximum),n))
        for j in range(count):
            start=cursor+round(duration*j/count); end=cursor+round(duration*(j+1)/count)
            sid=f'{idx:03d}_{j+1:02d}'
            if settings.constant_image_prompt is None:
                prompt=f"{plan['visual_bible']}\nStyle: {settings.style}. {scene['visual']}\n"
            else:
                prompt='\n'.join(part for part in (settings.constant_image_prompt,scene['visual'].strip()) if part)+'\n'
            prompt+=f'Composition {j+1} of {count}: '+(['establishing view','close-up detail','different camera angle'][j%3])
            prompt+=f'. Aspect ratio {settings.aspect}. No text, logos, captions or watermarks added by the artist. Keep recurring characters consistent. Keep important subjects away from edges.'
            shots.append({'id':sid,'scene':idx,'start':start,'duration':end-start,'prompt':prompt,'sound_context':scene.get('sfx_query','')+' '+scene['narration']+' '+scene['visual'],'sfx':scene['sfx'] and j==0})
        phrases=split_caption(scene['narration'],max_chars=24 if settings.aspect=='9:16' else 36); weights=[len(p.split()) for p in phrases]; total=sum(weights); used=0
        for p,w in zip(phrases,weights):
            a=cursor+round(duration*used/total); used+=w; b=cursor+round(duration*used/total)
            captions.append({'text':p,'start':a,'duration':b-a})
        if scene['overlay']: overlays.append({'text':scene['overlay'],'start':cursor,'duration':min(duration,3_000_000)})
        cursor+=duration
    exceptions=[]
    if settings.min_shot_seconds:
        minimum=settings.min_shot_seconds*1_000_000;maximum=settings.shot_seconds*1_000_000
        combined=[]
        for shot in shots:
            previous=combined[-1] if combined else None
            if previous:
                a=plan['scenes'][previous['scene']-1];b=plan['scenes'][shot['scene']-1]
                same_visual=' '.join(a['visual'].casefold().split())==' '.join(b['visual'].casefold().split())
                # Preserve distinct graphic ideas and sound-cue boundaries.
                if (same_visual and a.get('graphic')==b.get('graphic') and not shot['sfx'] and
                    min(previous['duration'],shot['duration'])<minimum and previous['duration']+shot['duration']<=maximum):
                    previous['duration']+=shot['duration']
                    previous.setdefault('source_scenes',[previous['scene']]).append(shot['scene'])
                    previous['sound_context']+=' '+shot['sound_context']
                    continue
            combined.append(shot)
        shots=combined
        exceptions=[{'shot_id':s['id'],'duration_seconds':s['duration']/1_000_000,
                     'reason':'Preserved narration and visual boundaries.'}
                    for s in shots if not minimum<=s['duration']<=maximum]
    return {'duration':cursor,'width':settings.dimensions[0],'height':settings.dimensions[1],
            'shots':shots,'captions':captions,'overlays':overlays,'caption_alignment':'Approximate word-weighted timing within measured narration beats.',
            **({'image_hold_exceptions':exceptions} if settings.min_shot_seconds else {})}
