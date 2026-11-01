"""Explicit optional installation; never changes VideoPilot's Kokoro environment."""
import os
import subprocess
import sys
import time
import venv
from .core import ROOT, DATA, atomic_json, read_json
from .cloned_voices import RUNTIME, MODEL_CACHE


def main():
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    ready = MODEL_CACHE / 'ready.json'
    ready.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update(HF_HOME=str(MODEL_CACHE), HF_HUB_DISABLE_XET='1',
               TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='2',
               MKL_NUM_THREADS='2', PYTHONUTF8='1')
    env.pop('HF_HUB_OFFLINE', None)
    def run(args):
        subprocess.run([str(x) for x in args], cwd=ROOT, env=env, check=True)
    print('Installing Chatterbox Nano in its own environment. Kokoro is unchanged.', flush=True)
    if not RUNTIME.is_file():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv-chatterbox')
    run([RUNTIME, '-m', 'pip', 'install', '--upgrade', 'pip'])
    run([RUNTIME, '-m', 'pip', 'install', 'torch==2.6.0', 'torchaudio==2.6.0',
         '--index-url', 'https://download.pytorch.org/whl/cpu'])
    # Nano is supported in the upstream source; older PyPI releases lack nano=True.
    run([RUNTIME, '-m', 'pip', 'install',
         'https://github.com/resemble-ai/chatterbox/archive/refs/heads/master.zip'])
    run([RUNTIME, '-m', 'pip', 'check'])
    print('Downloading Nano and testing voice cloning on this CPU...', flush=True)
    run([RUNTIME, '-c',
         "import torch; torch.set_num_threads(2); from chatterbox.tts_turbo import ChatterboxTurboTTS; ChatterboxTurboTTS.from_pretrained(device='cpu',nano=True)"])
    work = MODEL_CACHE / 'installation-test'
    work.mkdir(exist_ok=True)
    req = work / 'request.json'
    atomic_json(req, {'folder': str(work), 'models': str(DATA/'models'),
        'voice': 'af_alloy', 'language': 'en-us', 'speed': 1.,
        'scenes': ['Welcome to our story. Come and sit beside me, and I will tell you about a lovely afternoon in the garden, filled with sunshine and birdsong.']})
    run([sys.executable, '-m', 'videopilot.tts_worker', req])
    reference = work / 'reference.wav'
    os.replace(work/'001.wav', reference)
    request = read_json(req)
    request.update(voice='nano_'+'0'*32, reference=str(reference),
                   scenes=['Come on in, honey. Let me tell you a little story.'])
    atomic_json(req, request)
    started = time.monotonic()
    run([RUNTIME, '-m', 'videopilot.tts_worker', req])
    from .audio import wav_info
    seconds = wav_info(work/'001.wav')['duration']
    elapsed = time.monotonic()-started
    if seconds < 1:
        raise RuntimeError('Generation test produced unexpectedly short audio.')
    packages = subprocess.check_output([str(RUNTIME), '-m', 'pip', 'freeze'], env=env, text=True)
    (MODEL_CACHE/'installed-packages.txt').write_text(packages, encoding='utf-8')
    atomic_json(ready, {'model': 'Chatterbox Nano', 'device': 'cpu',
                       'test_seconds': seconds, 'elapsed_seconds': elapsed})
    print(f'Ready: generated {seconds:.1f}s audio in {elapsed:.1f}s including model loading.', flush=True)
    print(f'Listen to the test: {work / "001.wav"}', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'Chatterbox setup failed: {error}', file=sys.stderr)
        print(f'Generation details, if available: {MODEL_CACHE / "installation-test" / "progress.json"}', file=sys.stderr)
        sys.exit(1)
