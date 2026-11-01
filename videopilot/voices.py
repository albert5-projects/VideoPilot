"""English narrator choices from the installed Kokoro archive's index only."""
import re
from pathlib import Path
from zipfile import ZipFile,BadZipFile
from .core import DATA

ENGLISH_VOICES={
    'af':('alloy','aoede','bella','heart','jessica','kore','nicole','nova','river','sarah','sky'),
    'am':('adam','echo','eric','fenrir','liam','michael','onyx','puck','santa'),
    'bf':('alice','emma','isabella','lily'),
    'bm':('daniel','fable','george','lewis'),
}
GROUPS={'af':'US female','am':'US male','bf':'UK female','bm':'UK male'}


def english_voices(path=None):
    path=Path(path) if path is not None else DATA/'models/voices-v1.0.bin'
    fallback=[f'{prefix}_{name}' for prefix,names in ENGLISH_VOICES.items() for name in names]
    try:
        # NPZ is a ZIP of arrays. Listing its directory reads no voice tensors
        # and imports neither NumPy nor ONNX into the desktop process.
        with ZipFile(path) as archive:
            ids=sorted({name[:-4] for name in archive.namelist()
                if re.fullmatch(r'(?:af|am|bf|bm)_[a-z0-9_]+\.npy',name)})
    except (OSError,BadZipFile):ids=fallback
    return {f'{voice[3:].replace("_"," ").title()} \u00b7 {GROUPS[voice[:2]]}':voice for voice in (ids or fallback)}
