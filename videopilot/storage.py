"""Share byte-identical Flow originals and prune unused render cache."""
from pathlib import Path
from .core import UserError, read_json, file_hash
import os,uuid


def share_identical_file(source,destination):
    """Share immutable originals while retaining both names; fall back unchanged."""
    source=Path(source);destination=Path(destination)
    if source.samefile(destination):return 0
    if source.stat().st_size!=destination.stat().st_size or file_hash(source)!=file_hash(destination):return 0
    size=destination.stat().st_size if destination.stat().st_nlink==1 else 0
    temporary=destination.with_name(destination.name+'.link-'+uuid.uuid4().hex)
    try:
        os.link(source,temporary)
        os.replace(temporary,destination)
        return size
    except OSError:return 0  # Cross-volume or unsupported filesystem: retain the copy.
    finally:temporary.unlink(missing_ok=True)


def clean_duplicates(job):
    if (job.folder/'run.lock').exists(): raise UserError('Stop generation before cleaning project storage.')
    return share_flow_originals(job)


def share_flow_originals(job):
    """Deduplicate only raw Flow originals; edited images/backups stay independent."""
    from collections import defaultdict
    groups=defaultdict(list);root=job.folder.resolve()
    for folder in (root/'flow_variants',root/'browser-downloads'):
        if not folder.resolve().is_relative_to(root):raise UserError('Invalid Flow image folder.')
        for path in folder.rglob('*.png'):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()):
                groups[path.stat().st_size].append(path)
    saved=0
    for paths in groups.values():
        if len(paths)<2:continue
        hashes={}
        for path in paths:
            digest=file_hash(path)
            if digest in hashes:saved+=share_identical_file(hashes[digest],path)
            else:hashes[digest]=path
    return saved


def clean_unused_graphics(job):
    """Prune our hash-verified render cache only after a successful uninstalled build."""
    if job.data.get('installed_path') or (job.folder/'run.lock').exists():return 0
    referenced=set()
    if job.data.get('state')=='READY_FOR_KDENLIVE':
        draft=job.folder/'kdenlive/VideoPilot.kdenlive'
        if not draft.exists():return 0
        from xml.etree import ElementTree
        referenced={Path(p.text).resolve() for p in ElementTree.parse(draft).findall(".//property[@name='resource']") if p.text and p.text!='0'}
    else:
        draft=job.folder/'capcut'/'draft_content.json'
        if not draft.exists() or job.data.get('state')!='READY_FOR_CAPCUT':return 0
        data=read_json(draft)
        referenced={Path(m['path']).resolve() for m in data.get('materials',{}).get('videos',[]) if m.get('path')}
    report=job.folder/'graphics_report.json'
    if report.exists():referenced.update(Path(c['path']).resolve() for c in read_json(report).get('clips',{}).values())
    root=(job.folder/'graphics').resolve()
    if not root.is_relative_to(job.folder.resolve()):return 0
    import re
    removed=0
    for path in root.glob('*.mp4'):
        if not re.fullmatch(r'\d{3,}_\d{2,}-[0-9a-f]{16}\.mp4',path.name):continue
        if not path.resolve().is_relative_to(root) or path.resolve() in referenced:continue
        meta=path.with_suffix('.json')
        if not meta.is_file() or not meta.resolve().is_relative_to(root):continue
        if read_json(meta).get('sha256')!=file_hash(path):continue
        removed+=path.stat().st_size+meta.stat().st_size
        path.unlink();meta.unlink()
    return removed
