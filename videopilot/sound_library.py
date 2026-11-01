"""Import user-downloaded effects; no private CapCut endpoints or account access."""
import os, re, shutil, subprocess
from pathlib import Path
from .core import UserError, atomic_json, read_json, file_hash, fingerprint
from .audio import wav_info


def import_library(job, source, cancel, log):
    source=Path(source)
    if not source.is_dir(): raise UserError('Choose a folder containing downloaded sound effects.')
    dest=job.folder/'audio'/'effects'; dest.mkdir(parents=True,exist_ok=True)
    from .sound_catalog import discover,write_catalog
    catalog=discover(source,cancel);job.check(cancel)
    write_catalog(catalog,job.folder/'SOUND_LIBRARY_CATALOG.csv')
    entries=[]
    for item in catalog:
        if not item['name'] or item['kind']=='music' or item['size']>20*1024*1024:continue
        key=fingerprint([item['source'],item['size'],item['mtime_ns']])[:24]
        entries.append(dict(item,file=key+'.wav'))
    atomic_json(dest/'index.json',entries)
    named=sum(bool(x['name']) for x in catalog)
    log(f'{named}/{len(catalog)} audio files have names; {len(entries)} available as effects. Only used effects are copied. See SOUND_LIBRARY_CATALOG.csv for names and unidentified files.')


def materialize(root,item):
    target=root/item['file']
    if target.is_file():return target
    source=Path(item.get('source',''))
    if not source.is_file():return None
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise UserError('FFmpeg is required to prepare the selected sound effect.')
    tmp=target.with_suffix('.partial.wav')
    try:
        result=subprocess.run([ffmpeg,'-nostdin','-v','error','-y','-i',str(source),'-t','3','-vn',
            '-ac','1','-ar','24000','-threads','2','-c:a','pcm_s16le',str(tmp)],capture_output=True,timeout=30,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not tmp.exists() or wav_info(tmp)['duration']<=0:raise UserError('Could not decode sound effect: '+item['name'])
        os.replace(tmp,target);return target
    finally:tmp.unlink(missing_ok=True)


def select_sound(folder,shot):
    root=Path(folder)/'audio'/'effects'; index=root/'index.json'
    if not index.exists(): return None
    if 'sfx_file' in shot:
        name=shot['sfx_file']
        if name in ('','builtin'):return None
        item=next((s for s in read_json(index) if s.get('file')==name and Path(name).name==name),None)
        if not item:raise UserError('The Codex-selected sound is no longer available. Rebuild the editing plan.')
        selected=materialize(root,item)
        if selected is None:raise UserError('The Codex-selected sound file has been removed. Rebuild the editing plan.')
        return selected
    words=set(re.findall(r'[a-z]{3,}',(shot.get('sound_context') or shot.get('prompt','')).lower().replace('woosh','whoosh')))
    stop={'the','and','for','with','sound','effect','effects','sfx','audio'}
    ranked=[]
    for item in read_json(index):
        name=item.get('file','')
        if Path(name).name!=name: continue
        path=root/name
        label=' '.join(item.get('aliases') or [item['name']]).lower().replace('woosh','whoosh')
        score=len((set(re.findall(r'[a-z]{3,}',label))-stop)&words)
        if score and (path.is_file() or Path(item.get('source','')).is_file()): ranked.append((score,item['name'],item))
    return materialize(root,max(ranked,key=lambda x:(x[0],x[1]))[2]) if ranked else None
