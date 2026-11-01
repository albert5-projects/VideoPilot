"""Fetch only the two published Kokoro assets; never run downloaded scripts."""
import hashlib, os, urllib.request
from .core import DATA, atomic_json

BASE='https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
FILES=('kokoro-v1.0.onnx','voices-v1.0.bin')

def main():
    folder=DATA/'models'; folder.mkdir(parents=True,exist_ok=True)
    print('Downloads Kokoro model/voices from the official kokoro-onnx GitHub release.')
    print('Allow roughly 350 MB of downloads and 1 GB of free disk space for setup.')
    manifest={}
    for name in FILES:
        path=folder/name
        if path.exists():
            print(name,'already exists; leaving it unchanged. Delete it manually to download again.')
            continue
        part=path.with_suffix('.download'); size=0; h=hashlib.sha256()
        try:
            with urllib.request.urlopen(BASE+name,timeout=60) as response,part.open('wb') as out:
                if not response.url.startswith('https://'): raise RuntimeError('Refusing a non-HTTPS download.')
                while block:=response.read(1024*1024):
                    size+=len(block)
                    if size>500*1024*1024: raise RuntimeError('Download too large.')
                    h.update(block); out.write(block)
                    print(f'\r{name}: {size/1024/1024:.1f} MB',end='',flush=True)
            if size<100000: raise RuntimeError('Downloaded file unexpectedly small.')
            os.replace(part,path); print()
            manifest[name]={'url':BASE+name,'bytes':size,'sha256':h.hexdigest()}
        except Exception:
            part.unlink(missing_ok=True); raise
    if manifest: atomic_json(folder/'download_receipt.json',manifest)
    print('Files ready. SHA256 receipts record downloaded bytes; these are not independent publisher signature verification.')
if __name__=='__main__':
    try: main()
    except Exception as e: print('Download failed:',str(e)); raise SystemExit(1)
