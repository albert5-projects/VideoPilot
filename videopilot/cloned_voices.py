"""Local reference-voice library and isolated Chatterbox runtime selection."""
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from .core import DATA, ROOT, UserError, atomic_json, read_json

LIBRARY = DATA / 'cloned-voices'
RUNTIME = ROOT / '.venv-chatterbox' / 'Scripts' / 'python.exe'
MODEL_CACHE = ROOT / 'models' / 'chatterbox-cache'


def is_nano(voice):
    return bool(re.fullmatch(r'nano_[a-f0-9]{32}', voice))


def voices():
    result = {}
    for meta in sorted(LIBRARY.glob('nano_*.json')):
        try:
            if is_nano(meta.stem) and meta.with_suffix('.wav').is_file():
                result[f'Chatterbox Nano: {read_json(meta)["name"]} [{meta.stem[-6:]}]'] = meta.stem
        except (OSError, ValueError, KeyError):
            continue
    return result


def reference(voice, project=None):
    if not is_nano(voice):
        raise UserError('Choose a saved Chatterbox Nano voice.')
    if project is not None:
        saved = Path(project) / 'voice-reference' / (voice + '.wav')
        if saved.is_file():
            return saved
    source = LIBRARY / (voice + '.wav')
    if not source.is_file():
        raise UserError('This cloned voice was removed. Upload a sample or choose another voice.')
    if project is not None:
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, saved)
        return saved
    return source


def add_voice(source, name):
    from .audio import wav_info
    name = name.strip()[:80]
    if not name:
        raise UserError('Enter a name for this voice.')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise UserError('FFmpeg is required to import voice samples. Install it and restart VideoPilot.')
    LIBRARY.mkdir(parents=True, exist_ok=True)
    voice = 'nano_' + uuid.uuid4().hex
    out = LIBRARY / (voice + '.wav')
    try:
        result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source),
            '-t', '15', '-vn', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(out)],
            capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not out.is_file():
            raise UserError('Could not read this audio sample. Use a WAV, MP3, FLAC or M4A file.')
        if wav_info(out)['duration'] <= 5:
            raise UserError('Use more than 5 seconds of clear speech; 10–15 seconds is recommended.')
        import wave, array
        with wave.open(str(out), 'rb') as audio:
            samples = array.array('h', audio.readframes(audio.getnframes()))
        if not samples or max(abs(x) for x in samples) < 100:
            raise UserError('The sample is silent or too quiet. Choose clear spoken audio.')
        atomic_json(out.with_suffix('.json'), {'name': name})
    except Exception:
        out.unlink(missing_ok=True)
        raise
    return voice


def remove_voice(voice):
    if not is_nano(voice):
        raise UserError('Choose a cloned voice to remove.')
    (LIBRARY / (voice + '.json')).unlink(missing_ok=True)
    (LIBRARY / (voice + '.wav')).unlink(missing_ok=True)


def worker_python(voice):
    if not is_nano(voice):
        return sys.executable
    if not RUNTIME.is_file() or not (MODEL_CACHE / 'ready.json').is_file():
        raise UserError('Chatterbox Nano is not ready. Run Install_Chatterbox_Nano.bat, then try again.')
    return str(RUNTIME)


def worker_environment():
    return {'HF_HOME': str(MODEL_CACHE), 'HF_HUB_OFFLINE': '1',
            'HF_HUB_DISABLE_XET': '1', 'TOKENIZERS_PARALLELISM': 'false'}
