import ctypes
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from videopilot.core import atomic_json, read_json
from videopilot.tts_progress import write_progress


class ProgressTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows sharing behavior')
    def test_ui_reader_lock_does_not_abort_progress_or_completion(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'progress.json'
            atomic_json(path, {'message': 'Voice 32/200 reused'})
            for update in ({'message': 'Voice 33/200 reused'}, {'done': True}):
                handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
                self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
                try:
                    with self.assertRaises(PermissionError):atomic_json(path, update)
                except BaseException:
                    kernel.CloseHandle(handle)
                    raise
                release = threading.Timer(.1, lambda:kernel.CloseHandle(handle))
                release.start()
                try:write_progress(path, update)
                finally:release.join()
                self.assertEqual(read_json(path), update)

    def test_persistent_write_failure_is_not_hidden(self):
        with patch('videopilot.tts_progress.atomic_json', side_effect=PermissionError), patch('videopilot.tts_progress.time.sleep'):
            with self.assertRaises(PermissionError):write_progress('unused', {'done':True})
