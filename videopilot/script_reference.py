"""Load a user-selected writing reference without depending on its future path."""
from pathlib import Path
from .core import UserError


def read_sample_script(path):
    path=Path(path)
    if path.suffix.lower()!='.txt':raise UserError('Choose a .txt sample script.')
    try:
        if path.stat().st_size>1_000_000:raise UserError('Choose a sample script smaller than 1 MB.')
        raw=path.read_bytes()
        text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    except (OSError,UnicodeError) as error:
        raise UserError('Could not read the sample script. Save it as a UTF-8 .txt file and try again.') from error
    if not text.strip():raise UserError('The sample script is empty.')
    return text.strip()
