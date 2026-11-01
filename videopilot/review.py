"""Local-only storyboard; escapes all model/user text."""
import html
from pathlib import Path
from urllib.parse import quote
from .core import read_json, UserError, file_hash

def make_storyboard(job):
    path=job.folder/'timeline.json'
    if not path.exists(): raise UserError('Generate narration first to create a timed storyboard.')
    data=read_json(path); cards=[]
    report_path=job.folder/'graphics_report.json'
    report=read_json(report_path) if report_path.exists() else {}
    for s in data['shots']:
        p=job.folder/'images'/f'{s["id"]}.png'
        image=f'<img loading="lazy" src="images/{s["id"]}.png" alt="Shot {s["id"]}">' if p.exists() else '<div class="missing">Image needed</div>'
        rendered=report.get('clips',{}).get(s['id'])
        if rendered and (rendered.get('source_shot_id')!=s['id'] or not p.exists() or rendered.get('source_image_sha256')!=file_hash(p)):
            rendered=None
            image+='<p>Graphics need rebuilding or source verification; showing the current image.</p>'
        if rendered:
            video=Path(rendered['path']).resolve()
            if video.is_file() and video.is_relative_to(job.folder.resolve()):
                src=html.escape(quote(video.relative_to(job.folder.resolve()).as_posix()),quote=True)
                image=f'<video controls preload="none" style="width:100%;height:260px;object-fit:contain" poster="images/{s["id"]}.png" src="{src}"></video><p>Rendered graphic · last build</p>'
        cards.append(f'<article>{image}<h3>{s["id"]} · {s["start"]/1e6:.1f}s · {s["duration"]/1e6:.1f}s hold</h3><p>{html.escape(s["prompt"])}</p></article>')
    out=job.folder/'storyboard.html'
    out.write_text('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; media-src 'self' file:; style-src 'unsafe-inline'"><title>VideoPilot storyboard</title><style>body{background:#101722;color:#e6edf5;font:16px system-ui;margin:30px}h1{color:#9ad5cc}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}article{background:#1c2938;padding:14px;border-radius:14px}img,.missing{width:100%;height:260px;object-fit:contain;background:#080f18}p{font-size:13px;color:#aabbcc;white-space:pre-wrap}audio{width:min(650px,100%);margin:15px 0}small{display:block;margin-bottom:20px}</style></head><body><h1>VideoPilot · Storyboard</h1>'''+f'<small>Actual duration: {data["duration"]/1e6:.2f}s. Review imagery and pronunciation before completing the CapCut project. This is not a rendered video.</small><audio controls preload="none" src="audio/narration.wav"></audio><main>'+''.join(cards)+'</main></body></html>',encoding='utf-8')
    return out
