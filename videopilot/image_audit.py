"""Detect near-identical automatic imports before they become editor clips."""
from PIL import Image,ImageChops,ImageStat
from .core import atomic_json,read_json,UserError


def audit_images(job,timeline,report_path=None):
    samples=[];duplicates=[]
    for shot in timeline['shots']:
        path=job.folder/'images'/(shot['id']+'.png')
        meta=path.with_suffix('.json')
        if not path.is_file() or not meta.is_file():continue
        if read_json(meta).get('source')!='Google Flow browser helper':continue
        with Image.open(path) as im:sample=im.convert('RGB').resize((64,36),Image.Resampling.LANCZOS)
        # Flat illustrations can legitimately repeat. Check textured images only.
        if max(ImageStat.Stat(sample).stddev)<4:continue
        for previous,other in samples:
            if previous['prompt']==shot['prompt']:continue
            difference=ImageStat.Stat(ImageChops.difference(sample,other))
            if max(difference.mean)<=1.5 and max(difference.rms)<=5:
                duplicates.append({'shots':[previous['id'],shot['id']], 'mean_difference':difference.mean})
        samples.append((shot,sample))
    report={'near_duplicate_automatic_imports':duplicates,'checked_images':len(samples)}
    atomic_json(report_path or job.folder/'IMAGE_ASSIGNMENT_REVIEW.json',report)
    return report


def require_distinct_imports(job,timeline):
    report=audit_images(job,timeline)
    if report['near_duplicate_automatic_imports']:
        pairs='; '.join(' / '.join(x['shots']) for x in report['near_duplicate_automatic_imports'])
        raise UserError('Nearly identical Flow images have different prompts: '+pairs+'. Review these shots before building. Import the correct images by shot filename. If repetition is intentional, confirm a variant with Use selected. See IMAGE_ASSIGNMENT_REVIEW.json. No draft was rebuilt.')


def create_image_repair_copy(source,cancel,log,root=None):
    """Reuse prepared assets without modifying an installed editor project."""
    import shutil
    from dataclasses import replace
    from .core import Job
    for name in ('script.json','timeline.json','captions.srt','audio/narration.wav'):
        if not (source.folder/name).is_file():raise UserError('Prepare narration before creating an image-repair copy.')
    source.check(cancel)
    target=Job.create(replace(source.settings),root)
    for name in ('script.json','script.txt','timeline.json','captions.srt'):
        source.check(cancel)
        if (source.folder/name).is_file():shutil.copy2(source.folder/name,target.folder/name)
    for name in ('audio','images','flow_variants'):
        source.check(cancel)
        if (source.folder/name).is_dir():shutil.copytree(source.folder/name,target.folder/name)
    for key in ('prepared_signature','prepared_hashes','actual_duration','effective_speed','script_origin','voice_plan_signature','auto_fit_attempts','image_requests'):
        if key in source.data:target.data[key]=source.data[key]
    target.data['image_repair_source']=str(source.folder)
    from .flow import queue_for
    queue_for(target,read_json(target.folder/'timeline.json'))
    target.status('IMAGES_IMPORTED','Image-repair copy ready. Import corrected shot images, then Continue project. Script and narration are reused.')
    log('Created image-repair copy; the installed edit is unchanged. Correct images here, Continue, and install into a new empty editor project.')
    return target
