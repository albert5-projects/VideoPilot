"""Recover audio names from local tags and native CapCut draft metadata."""
import csv, json, re
from pathlib import Path

FORMATS={'.wav','.mp3','.m4a','.ogg','.aac','.flac'}


def meaningful(value):
    value=str(value or '').strip()
    return bool(value and not re.fullmatch(r'[a-fA-F0-9]{16,}(?:\.\w+)?',value) and len(value)<=500)


def id3_title(path):
    """Read bounded ID3 title frames; no decoding or external process per file."""
    if path.suffix.lower()!='.mp3':return ''
    with path.open('rb') as f:data=f.read(131072)
    if data[:3]!=b'ID3' or len(data)<10 or data[3] not in (3,4):return ''
    version=data[3];offset=10
    if data[5]&0x40:return '' # Unknown extended header: rely on native metadata.
    while offset+10<=len(data):
        frame=data[offset:offset+4];raw=data[offset+4:offset+8]
        size=sum((n&127)<<(7*(3-i)) for i,n in enumerate(raw)) if version==4 else int.from_bytes(raw,'big')
        if not size or size>len(data)-offset-10:break
        payload=data[offset+10:offset+10+size]
        if frame==b'TIT2' and payload:
            encoding={0:'latin1',1:'utf-16',2:'utf-16-be',3:'utf-8'}.get(payload[0])
            if encoding:
                try:return payload[1:].decode(encoding).strip('\0 \ufeff')
                except UnicodeError:return ''
        offset+=10+size
    return ''


def discover(source,cancel=None):
    source=Path(source).resolve();draft_names={}
    is_capcut_cache=source.name.lower()=='music' and source.parent.name.lower()=='cache'
    if is_capcut_cache:
        projects=source.parent.parent/'Projects'/'com.lveditor.draft'
        for draft in projects.glob('*/draft_content.json'):
            if cancel and cancel.is_set():break
            try:
                if draft.stat().st_size>32*1024*1024:continue
                data=json.loads(draft.read_text(encoding='utf-8-sig'))
                for audio in data.get('materials',{}).get('audios',[]):
                    name=audio.get('name') or audio.get('material_name','')
                    filename=Path(audio.get('path','').replace('\\','/')).name
                    if filename and meaningful(name):
                        entry=draft_names.setdefault(filename,{'names':set(),'kind':'unknown'})
                        entry['names'].add(name)
                        if audio.get('type') in ('sound','music'):entry['kind']=audio['type']
            except (OSError,ValueError,TypeError):continue
    entries=[]
    for path in sorted(source.iterdir()):
        if cancel and cancel.is_set():break
        if not path.is_file() or path.suffix.lower() not in FORMATS:continue
        try:
            stat=path.stat()
            title=id3_title(path) if path.name not in draft_names else ''
        except OSError:continue # CapCut may replace a download during discovery.
        entry=draft_names.get(path.name)
        if entry:
            aliases=sorted(entry['names']);name=aliases[0];origin='CapCut draft metadata';kind=entry['kind']
        else:
            name=title if meaningful(title) else path.stem if meaningful(path.stem) else ''
            aliases=[name] if name else [];origin='ID3 title' if meaningful(title) else 'filename' if name else 'unresolved';kind='unknown'
        entries.append({'name':name,'aliases':aliases,'source':str(path),'name_source':origin,'kind':kind,
            'size':stat.st_size,'mtime_ns':stat.st_mtime_ns})
    return entries


def write_catalog(entries,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['Name','Name source','Kind','Original filename','Full path'])
        for item in entries:
            row=[item['name'] or '(unidentified)',item['name_source'],item['kind'],Path(item['source']).name,item['source']]
            # Avoid spreadsheet formula execution from imported metadata.
            writer.writerow(["'"+x if x.startswith(('=','+','-','@')) else x for x in row])
