import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from videopilot.gui import App

class MusicPickerTests(unittest.TestCase):
    def test_browse_selects_file_mode(self):
        app=SimpleNamespace(vars={'bgm_path':Mock(),'bgm':Mock()})
        with patch('videopilot.gui.filedialog.askopenfilename',return_value='C:/Music/my-song.mp3'):
            App.browse(app,'bgm_path')
        app.vars['bgm'].set.assert_called_once_with('file')
        app.vars['bgm_path'].set.assert_called_once_with('C:/Music/my-song.mp3')

    def test_cancel_preserves_music(self):
        app=SimpleNamespace(vars={'bgm_path':Mock(),'bgm':Mock()})
        with patch('videopilot.gui.filedialog.askopenfilename',return_value=''):
            App.browse(app,'bgm_path')
        app.vars['bgm'].set.assert_not_called()
        app.vars['bgm_path'].set.assert_not_called()
