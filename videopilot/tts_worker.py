"""Invoked in a subprocess so ONNX memory is released before editing."""
import os, sys, wave
from pathlib import Path
from .core import atomic_json, read_json, fingerprint, file_hash
from .tts_progress import write_progress

def main(request_path):
    request=read_json(request_path); folder=Path(request['folder']); progress=folder/'progress.json'
    try:
        import numpy as np
        from .cloned_voices import is_nano
        nano=is_nano(request['voice'])
        if nano:
            from .nano_voice import NanoVoice, narration_signature
            reference_hash=file_hash(request['reference'])
            kokoro=None
        else:
            from .kokoro_compat import TypedKokoro
            model=Path(request['models'])/'kokoro-v1.0.onnx'; voices=model.with_name('voices-v1.0.bin')
            if not model.is_file() or not voices.is_file(): raise RuntimeError('Kokoro files are missing. Run Download_Models.bat first.')
            write_progress(progress,{'message':'Loading local Kokoro voice model…'})
            # Explicit CPU session and two threads to leave room for Windows on an 8 GB PC.
            import onnxruntime as ort
            opts=ort.SessionOptions(); opts.intra_op_num_threads=2; opts.inter_op_num_threads=1
            session=ort.InferenceSession(str(model),sess_options=opts,providers=['CPUExecutionProvider'])
            kokoro=TypedKokoro.from_session(session,str(voices))
        for i,text in enumerate(request['scenes'],1):
            path=folder/f'{i:03d}.wav'; meta=folder/f'{i:03d}.json'
            sig=narration_signature(text,reference_hash,request['speed']) if nano else fingerprint(['tight-pauses-v1',text,request['voice'],request['speed'],request['language'],model.stat().st_size,voices.stat().st_size])
            if path.exists() and meta.exists() and read_json(meta).get('signature')==sig:
                # Validate cached bytes, not only presence.
                if read_json(meta).get('sha256')==file_hash(path):
                    write_progress(progress,{'message':f'Voice {i}/{len(request["scenes"])} reused'}); continue
            if nano and kokoro is None:
                kokoro=NanoVoice(request,progress)
            write_progress(progress,{'message':f'Generating voice {i}/{len(request["scenes"])}'})
            samples,rate=kokoro.create(text,voice=request['voice'],speed=request['speed'],lang=request['language'])
            samples=np.asarray(samples,dtype=np.float32).reshape(-1)
            if samples.size==0 or not np.isfinite(samples).all(): raise RuntimeError('TTS produced invalid audio.')
            from .audio import compact_silence
            original_frames=len(samples)
            samples=compact_silence(samples,rate)
            # Common fixed gain: no per-beat loudness pumping. Limit clipping only.
            samples=np.clip(samples,-.98,.98)
            n=min(120,len(samples)//2); samples[:n]*=np.linspace(0,1,n); samples[-n:]*=np.linspace(1,0,n)
            tmp=path.with_suffix('.partial.wav')
            with wave.open(str(tmp),'wb') as w:
                w.setparams((1,2,rate,0,'NONE','not compressed')); w.writeframes((samples*32767).astype('<i2').tobytes())
            os.replace(tmp,path)
            atomic_json(meta,{'signature':sig,'sha256':file_hash(path),'silence_removed_seconds':(original_frames-len(samples))/rate})
        write_progress(progress,{'done':True,'message':'Narration ready; TTS memory released on exit.'})
        return 0
    except Exception as e:
        # TTS handles only local paths/text and has no API credentials.
        write_progress(progress,{'done':False,'message':f'Local TTS: {type(e).__name__}: {str(e)[:350]}'})
        return 1

if __name__=='__main__': sys.exit(main(sys.argv[1]))
