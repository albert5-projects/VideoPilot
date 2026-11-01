"""File-only bridge to a user-invoked Flow browser helper. No server or credentials."""
from pathlib import Path
import os, shutil
from .core import atomic_json, read_json, fingerprint, file_hash, UserError

FLOW_URL='https://labs.google/fx/tools/flow'


def queue_for(job,timeline):
    payload={'version':1,'project':job.folder.name,'aspect':job.settings.aspect,
             'outputs':job.settings.flow_outputs,'shots':[{'id':s['id'],'prompt':s['prompt']} for s in timeline['shots']]}
    payload['queue_id']=fingerprint(payload)[:24]
    payload['download_folder']='VideoPilot/'+payload['queue_id']
    atomic_json(job.folder/'FLOW_QUEUE.json',payload)
    return payload


def default_downloads():
    # Windows Known Folder API honors redirected Downloads folders (e.g. another disk).
    if os.name=='nt':
        try:
            import ctypes, uuid
            from ctypes import wintypes
            raw=uuid.UUID('374DE290-123F-4565-9164-39C4925E467B').bytes_le
            guid=(ctypes.c_ubyte*16).from_buffer_copy(raw); result=ctypes.c_wchar_p()
            shell=ctypes.windll.shell32; shell.SHGetKnownFolderPath.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.HANDLE,ctypes.POINTER(ctypes.c_wchar_p)]
            if shell.SHGetKnownFolderPath(ctypes.byref(guid),0,None,ctypes.byref(result))==0:
                folder=Path(result.value); ctypes.windll.ole32.CoTaskMemFree(result); return folder
        except (OSError,AttributeError,ValueError): pass
    return Path.home()/'Downloads'


def collect_downloads(job,download_root=None,shot_ids=None,replace_existing=False):
    """Import only completed, receipt-matched images for this exact prompt queue."""
    job.require_mutable()
    if not (job.folder/'FLOW_QUEUE.json').exists(): return 0
    if download_root is None:
        roots=[job.folder/'browser-downloads',Path(job.settings.flow_downloads or default_downloads())]
        return sum(collect_downloads(job,root,shot_ids,replace_existing) for root in dict.fromkeys(roots))
    queue=read_json(job.folder/'FLOW_QUEUE.json'); timeline=read_json(job.folder/'timeline.json')
    root=Path(download_root or job.settings.flow_downloads or default_downloads())/'VideoPilot'/queue['queue_id']
    if not root.is_dir(): return 0
    from .pipeline import image_signature, cached_image
    from PIL import Image, ImageOps
    dest=job.folder/'images'; dest.mkdir(exist_ok=True)
    count=0
    for shot in timeline['shots']:
        if shot_ids is not None and shot['id'] not in shot_ids: continue
        if cached_image(job,shot) and not replace_existing: continue
        receipt=root/f'{shot["id"]}.receipt.json'
        if not receipt.is_file(): continue
        try: data=read_json(receipt)
        except (OSError,ValueError): continue  # browser still writing
        if data.get('queue_id')!=queue['queue_id'] or data.get('shot_id')!=shot['id']: continue
        if data.get('complete') is not True: continue
        if data.get('source')=='Flow signed-in browser':
            # Older browser receipts may contain the very assignment recovery
            # is meant to repair. Require fresh matching evidence and bytes.
            from .flow_browser import normalize
            from hashlib import sha256
            if data.get('matching_version')!=5 or data.get('prompt_hash')!=sha256(normalize(shot['prompt']).encode()).hexdigest():continue
        variants=data.get('variants',[])
        if not isinstance(variants,list) or not queue['outputs']<=len(variants)<=48: continue
        accepted=[]
        for v in variants:
            if not isinstance(v,dict): break
            name=v.get('filename','')
            # Names must be data, not traversable paths. Extension saves PNG/JPEG/WebP bytes with .png suffix;
            # Pillow detects and validates their actual format before normalizing.
            allowed=[f'{shot["id"]}__v{i}.png' for i in range(1,len(variants)+1)]
            if name not in allowed or name in [p.name for p in accepted]: break
            source=root/name
            if not source.is_file() or source.with_suffix(source.suffix+'.crdownload').exists(): break
            if data.get('source')=='Flow signed-in browser' and v.get('sha256')!=file_hash(source):break
            try:
                with Image.open(source) as im:
                    if im.format not in ('PNG','JPEG','WEBP') or min(im.size)<512: break
                    if abs((im.width/im.height)/(job.settings.dimensions[0]/job.settings.dimensions[1])-1)>.10: break
                    im.verify()
            except (OSError,ValueError): break
            accepted.append(source)
        if len(accepted)!=len(variants): continue
        if replace_existing:
            old=dest/f'{shot["id"]}.png'
            if old.is_file():
                backup=job.folder/'flow_repair_backups'/(shot['id']+'-'+file_hash(old)[:16])
                backup.mkdir(parents=True,exist_ok=True)
                for source in (old,old.with_suffix('.json')):
                    if source.is_file() and not (backup/source.name).exists():shutil.copy2(source,backup/source.name)
        # Preserve variants and normalized selection. No model judges image quality here.
        variant_dir=job.folder/'flow_variants'/shot['id']; variant_dir.mkdir(parents=True,exist_ok=True)
        for i,source in enumerate(accepted,1):
            variant=variant_dir/f'v{i}.png';temporary=variant.with_suffix('.partial.png')
            with Image.open(source) as im: im.convert('RGB').save(temporary,'PNG')
            os.replace(temporary,variant)
            if source.resolve().is_relative_to((job.folder/'browser-downloads').resolve()):
                from .storage import share_identical_file
                share_identical_file(source,variant)
        source=accepted[0]; path=dest/f'{shot["id"]}.png'
        with Image.open(source) as im:
            from .image_cleanup import clean_flow_star
            im,cleanup=clean_flow_star(ImageOps.exif_transpose(im))
            im=ImageOps.fit(im,job.settings.dimensions,method=Image.Resampling.LANCZOS)
            tmp=path.with_suffix('.partial.png'); im.save(tmp,'PNG'); os.replace(tmp,path)
        atomic_json(path.with_suffix('.json'),{'signature':image_signature(job,shot),'sha256':file_hash(path),
                    'source':'Google Flow browser helper','matching_version':data.get('matching_version'),'selected_variant':1,'queue_id':queue['queue_id'],'visible_star_cleanup':cleanup})
        count+=1
    return count


def choose_variant(job,shot_id,variant):
    job.require_mutable()
    timeline=read_json(job.folder/'timeline.json'); shot=next((s for s in timeline['shots'] if s['id']==shot_id),None)
    if not shot or not isinstance(variant,int) or not 1<=variant<=48: raise UserError('Choose a valid shot and variant.')
    source=job.folder/'flow_variants'/shot_id/f'v{variant}.png'
    if not source.exists(): raise UserError('This image variant has not been downloaded.')
    from PIL import Image,ImageOps
    from .pipeline import image_signature
    dest=job.folder/'images'/f'{shot_id}.png'
    with Image.open(source) as im:
        from .image_cleanup import clean_flow_star
        im,cleanup=clean_flow_star(ImageOps.exif_transpose(im))
        im=ImageOps.fit(im,job.settings.dimensions,method=Image.Resampling.LANCZOS); im.save(dest,'PNG')
    atomic_json(dest.with_suffix('.json'),{'signature':image_signature(job,shot),'sha256':file_hash(dest),'source':'Google Flow selected variant','selected_variant':variant,'visible_star_cleanup':cleanup})
    job.status('IMAGES_IMPORTED','Image selection updated. Continue to rebuild the draft.')
