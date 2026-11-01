import importlib.util, platform, shutil
from .core import DATA

def main():
    print('VideoPilot diagnostics (no credentials are read)')
    print('Python:',platform.python_version(),'OS:',platform.system())
    missing=[]
    for name in ('tkinter','numpy','PIL','kokoro_onnx','onnxruntime','keyring','playwright'):
        ok=importlib.util.find_spec(name) is not None
        print(name,':','OK' if ok else 'MISSING')
        if not ok: missing.append(name)
    print('Codex:', 'found' if shutil.which('codex') else 'not found — install separately / restart after adding PATH')
    print('Model files:', 'ready' if all((DATA/'models'/x).is_file() for x in ('kokoro-v1.0.onnx','voices-v1.0.bin')) else 'run Download_Models.bat')
    print('Project folder:',DATA/'projects')
    return bool(missing)
if __name__=='__main__': raise SystemExit(main())
