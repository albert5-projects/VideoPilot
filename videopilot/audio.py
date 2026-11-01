"""Bounded-memory PCM processing and a separate TTS worker."""
from __future__ import annotations
import math, os, subprocess, sys, time, wave
from pathlib import Path
from .core import ROOT, DATA, UserError, Cancelled, atomic_json, read_json, fingerprint


def compact_silence(samples, rate):
    """Shorten only sustained near-silence; retain speech and boundary handles."""
    import numpy as np
    samples=np.asarray(samples,dtype=np.float32).reshape(-1)
    if not len(samples) or np.max(np.abs(samples))<.0032:
        raise UserError('Narration contains no audible speech.')
    hop=max(1,round(rate*.01))
    quiet=np.array([np.max(np.abs(samples[i:i+hop])) < .0032
                    for i in range(0,len(samples),hop)])
    cuts=[]; i=0
    while i<len(quiet):
        if not quiet[i]: i+=1; continue
        j=i+1
        while j<len(quiet) and quiet[j]: j+=1
        a=i*hop; b=min(j*hop,len(samples))
        boundary=a==0 or b==len(samples)
        if b-a>=round(rate*(.12 if boundary else .35)):
            # Leave 90 ms next to each word; 180 ms total internal pause.
            left=0 if a==0 else round(rate*.09)
            right=0 if b==len(samples) else round(rate*.09)
            if a==0 and b==len(samples):
                raise UserError('Narration contains no audible speech.')
            cuts.append((a+left,b-right))
        i=j
    chunks=[]; cursor=0
    for a,b in cuts:
        chunks.append(samples[cursor:a]); cursor=b
    chunks.append(samples[cursor:])
    return np.concatenate(chunks) if cuts else samples

def wav_info(path):
    try:
        with wave.open(str(path),'rb') as w:
            if w.getsampwidth()!=2 or w.getcomptype()!='NONE': raise UserError('Use uncompressed 16-bit PCM WAV audio.')
            return {'frames':w.getnframes(),'rate':w.getframerate(),'channels':w.getnchannels(),'duration':w.getnframes()/w.getframerate()}
    except (wave.Error,EOFError) as e: raise UserError('Invalid WAV file: '+Path(path).name) from e


def audio_info(path):
    """Measure compressed audio without expanding it to a long PCM file."""
    if Path(path).suffix.lower()=='.wav':return wav_info(path)
    import json,shutil
    probe=shutil.which('ffprobe')
    if not probe:raise UserError('FFmpeg/FFprobe is required to read MP3 audio. Restart VideoPilot after installing it.')
    result=subprocess.run([probe,'-v','error','-select_streams','a:0','-show_entries',
        'stream=codec_type,sample_rate,channels:format=duration','-of','json',str(path)],
        capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        data=json.loads(result.stdout);stream=data['streams'][0];seconds=float(data['format']['duration'])
        if result.returncode or stream['codec_type']!='audio' or not math.isfinite(seconds) or seconds<=0:raise ValueError()
        return {'duration':seconds,'rate':int(stream['sample_rate']),'channels':int(stream['channels'])}
    except (ValueError,KeyError,IndexError):raise UserError('Cannot read audio: '+Path(path).name) from None


def background_path(folder,settings):
    suffix='.mp3' if settings.bgm=='file' and Path(settings.bgm_path).suffix.lower()=='.mp3' else '.wav'
    return Path(folder)/'audio'/('music'+suffix)


def duration_tolerance(target):
    """A requested runtime is a guide: allow modest drift in either direction."""
    return max(2.,min(15.,target*.10))


def synthesize(job, plan, speed, cancel, log):
    audio=job.folder/'audio'; audio.mkdir(exist_ok=True)
    request={'scenes':[s['narration'] for s in plan['scenes']], 'voice':job.settings.voice,
             'language':job.settings.language,'speed':speed,'models':str(DATA/'models'),'folder':str(audio)}
    from .cloned_voices import is_nano,reference,worker_python,worker_environment
    executable=worker_python(job.settings.voice)
    if is_nano(job.settings.voice):request['reference']=str(reference(job.settings.voice,job.folder))
    atomic_json(job.folder/'tts_request.json',request)
    progress=audio/'progress.json'; progress.unlink(missing_ok=True)
    env=os.environ.copy(); env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',PYTHONUTF8='1')
    if is_nano(job.settings.voice):env.update(worker_environment())
    p=subprocess.Popen([executable,'-m','videopilot.tts_worker',str(job.folder/'tts_request.json')],cwd=ROOT,env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    last=''; deadline=time.monotonic()+max(600,job.settings.duration*8)
    try:
        while p.poll() is None:
            if cancel.wait(.3): raise Cancelled('Narration stopped. Completed narration beats were saved.')
            if time.monotonic()>deadline: raise UserError('TTS worker timed out. Close heavy apps and retry.')
            if progress.exists():
                try:
                    message=read_json(progress).get('message','')
                    if message!=last: log(message); last=message
                except (OSError,ValueError): pass
    finally:
        if p.poll() is None:
            p.terminate()
            try: p.wait(5)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
    result=read_json(progress) if progress.exists() else {}
    if p.returncode or not result.get('done'):
        if result.get('done') is False:
            raise UserError(result.get('message','Local TTS generation failed.'))
        raise UserError(f'The narration worker stopped unexpectedly (exit code {p.returncode}). '
                        'Completed narration is saved. Continue project to reuse it. '
                        'Last progress: '+result.get('message','No progress reported.'))
    files=[audio/f'{i:03d}.wav' for i in range(1,len(plan['scenes'])+1)]
    return files,[wav_info(p)['duration'] for p in files]


def join_wavs(files,destination):
    if not files: raise UserError('No narration files.')
    expected=wav_info(files[0]); tmp=Path(destination).with_suffix('.partial.wav')
    with wave.open(str(tmp),'wb') as out:
        out.setparams((expected['channels'],2,expected['rate'],0,'NONE','not compressed'))
        for path in files:
            info=wav_info(path)
            if (info['channels'],info['rate'])!=(expected['channels'],expected['rate']): raise UserError('Narration WAV formats do not match.')
            with wave.open(str(path),'rb') as source:
                while data:=source.readframes(65536): out.writeframesraw(data)
    os.replace(tmp,destination)


def generated_ambient(path,seconds,cancel):
    """Simple original drone, not AI-composed music. Stream one second at a time."""
    import numpy as np
    rate=24000; frames=round(seconds*rate); tmp=Path(path).with_suffix('.partial.wav')
    with wave.open(str(tmp),'wb') as w:
        w.setparams((1,2,rate,0,'NONE','not compressed'))
        for start in range(0,frames,rate):
            if cancel.is_set(): raise Cancelled('Stopped ambient audio generation.')
            t=np.arange(start,min(start+rate,frames),dtype=np.float64)/rate
            envelope=np.minimum(np.minimum(t/2,(seconds-t)/2),1).clip(0,1)
            signal=sum(np.sin(2*np.pi*f*t)*a for f,a in ((110,.40),(164.81,.23),(220,.14),(329.63,.08)))
            signal*=envelope*(.8+.2*np.sin(2*np.pi*.07*t))*.18
            w.writeframesraw((signal*32767).astype('<i2').tobytes())
    os.replace(tmp,path)


def generated_whoosh(path):
    import numpy as np
    rate=24000; n=int(.28*rate); rng=np.random.default_rng(23)
    noise=rng.normal(0,1,n); smooth=np.convolve(noise,np.ones(7)/7,mode='same')
    samples=smooth*np.sin(np.linspace(0,np.pi,n))**2*.25
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,rate,0,'NONE','not compressed')); w.writeframes((samples*32767).clip(-32767,32767).astype('<i2').tobytes())
