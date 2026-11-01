"""Replan in a new project without changing media referenced by an existing edit."""
from dataclasses import replace
from .core import Job, read_json, atomic_json
from .providers import plan_video


def create_revision(source,cancel,log,root=None):
    settings=replace(source.settings)
    job=Job.create(settings,root)
    job.data['revision_of']=str(source.folder); job.save()
    previous=source.folder/'script.json'
    feedback='Replan as single visual ideas, cutting on every change of narrated subject or action. Preserve the story, facts and visual identity.'
    if previous.exists():
        import json
        feedback+=' Previous script: '+json.dumps(read_json(previous),ensure_ascii=False)
    log('Planning the revised edit in '+str(job.folder))
    try:
        plan=plan_video(settings,job.folder/'planner',cancel,feedback)
        atomic_json(job.folder/'script.json',plan)
        job.data['script_origin']='codex'
        job.status('SCRIPT_READY','Editing revision ready. Review the new beats, then Continue project and generate their Flow images.')
    except Exception:
        job.status('ERROR','Revision planning stopped. Original project is unchanged. Open this revision to retry.')
        raise
    return job
