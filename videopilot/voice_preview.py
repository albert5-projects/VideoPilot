"""Short cached previews; the Kokoro model lives only in a worker process."""
import os,sys,subprocess,tempfile,time,wave
from pathlib import Path
from .core import DATA,ROOT,UserError,Cancelled,atomic_json,read_json,fingerprint
from .voices import english_voices

TEXT='Hello, this is a sample of my voice. Listen to the tone, clarity, and rhythm as I tell your story in a natural and engaging way.'

def preview_voice(voice,cancel,log,folder=None,project=None):
    from .cloned_voices import is_nano,reference,worker_python,worker_environment
    nano=is_nano(voice)
    executable=worker_python(voice)
    ref=reference(voice,project) if nano else None
    if not nano and voice not in english_voices().values():raise UserError('Choose an installed English voice.')
    models=DATA/'models';model=models/'kokoro-v1.0.onnx';voices=models/'voices-v1.0.bin'
    if not nano and (not model.is_file() or not voices.is_file()):raise UserError('Run Download_Models.bat before previewing voices.')
    folder=Path(folder or DATA/'voice-previews');folder.mkdir(parents=True,exist_ok=True)
    # One small WAV per voice; a metadata stamp refreshes outdated previews.
    out=folder/(voice+'.wav');meta=out.with_suffix('.json')
    from .core import file_hash
    signature=fingerprint([TEXT,'nano-v1',file_hash(ref)]) if nano else fingerprint([TEXT,model.stat().st_size,model.stat().st_mtime_ns,voices.stat().st_mtime_ns])
    if out.exists() and meta.exists():
        try:
            with wave.open(str(out),'rb') as w:valid=w.getnframes()==6*w.getframerate()
            if valid and read_json(meta).get('signature')==signature:return out
        except (OSError,ValueError,wave.Error):pass
    with tempfile.TemporaryDirectory(prefix='preview-',dir=folder) as temporary:
        work=Path(temporary);request=work/'request.json'
        atomic_json(request,{'folder':str(work),'models':str(models),'voice':voice,'language':'en-gb' if voice.startswith('b') else 'en-us','speed':1.,'scenes':[TEXT],**({'reference':str(ref)} if nano else {})})
        env=os.environ.copy();env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',PYTHONUTF8='1')
        if nano:env.update(worker_environment())
        log('Preparing a six-second voice sample...')
        proc=subprocess.Popen([executable,'-m','videopilot.tts_worker',str(request)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        end=time.monotonic()+(600 if nano else 120)
        try:
            while proc.poll() is None:
                if cancel.wait(.2):raise Cancelled('Voice preview stopped.')
                if time.monotonic()>end:raise UserError('Voice preview timed out.')
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        if proc.returncode:
            progress=work/'progress.json';raise UserError(read_json(progress).get('message','Voice preview failed.') if progress.exists() else 'Voice preview failed.')
        import array
        with wave.open(str(work/'001.wav'),'rb') as w:
            rate=w.getframerate();samples=array.array('h',w.readframes(rate*6))
        wanted=rate*6
        if len(samples)<wanted:samples.extend([0]*(wanted-len(samples)))
        for i in range(min(480,len(samples))):samples[-1-i]=round(samples[-1-i]*i/480)
        temp=out.with_suffix('.partial.wav')
        with wave.open(str(temp),'wb') as w:w.setparams((1,2,rate,0,'NONE','not compressed'));w.writeframes(samples.tobytes())
        os.replace(temp,out);atomic_json(meta,{'signature':signature,'seconds':6,'voice':voice})
    return out
