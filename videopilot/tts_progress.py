"""Progress updates tolerate brief Windows reader locks."""
import time
from .core import atomic_json


def write_progress(path, data):
    # Windows may deny replacing progress.json while the UI reads it.
    # Keep atomic replacement, but let that short-lived handle close first.
    for attempt in range(101):
        try:
            atomic_json(path, data)
            return
        except PermissionError:
            if attempt == 100:
                raise
            time.sleep(.02)
