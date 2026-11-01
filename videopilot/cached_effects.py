"""Reuse native transition records with existing local packages; copy no cache."""
import os,json
from pathlib import Path
from copy import deepcopy


def native_transition(root=None):
    root=Path(root or Path(os.environ.get('LOCALAPPDATA',''))/'CapCut/User Data')
    cache=(root/'Cache/effect').resolve()
    for path in sorted((root/'Projects/com.lveditor.draft').glob('*/draft_content.json')):
        try:
            if path.stat().st_size>20*1024*1024:continue
            draft=json.loads(path.read_text(encoding='utf-8'))
            for material in draft.get('materials',{}).get('transitions',[]):
                if material.get('type')!='transition' or material.get('name','').lower() not in ('woosh','flash'):continue
                package=Path(material.get('path','')).resolve()
                if not package.is_relative_to(cache) or not package.is_dir():continue
                # Use only records actually referenced by a native video segment.
                if not any(material.get('id') in s.get('extra_material_refs',[]) for t in draft.get('tracks',[]) if t.get('type')=='video' for s in t.get('segments',[])):continue
                return deepcopy(material)
        except (OSError,ValueError,TypeError):continue
    return None
