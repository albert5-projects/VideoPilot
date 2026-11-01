import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from videopilot import image_cleanup as C
from videopilot.core import read_json


class FlowStarProfileTests(unittest.TestCase):
    def test_saved_position_removes_faint_mark_without_detection(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(C,'FLOW_STAR_PROFILES',Path(tmp)/'profiles.json'):
            base=np.full((768,768,3),50,dtype=np.uint8)
            marked=base.copy();marked[648:696,648:696][C._star(48)>0]=190
            _,report=C.clean_flow_star(Image.fromarray(marked))
            self.assertEqual(report['status'],'cleaned')
            profile=read_json(C.FLOW_STAR_PROFILES)['768x768']
            faint=base.copy();faint[648:696,648:696][C._star(48)>0]=57
            with patch.object(C,'detect_star',side_effect=AssertionError('Must reuse location')):
                result,report=C.clean_flow_star(Image.fromarray(faint))
            self.assertEqual(report['position_source'],'saved Flow profile')
            self.assertLess(np.abs(np.array(result).astype(float)-base).sum(),np.abs(faint.astype(float)-base).sum())
            np.testing.assert_array_equal(np.array(result)[:630],base[:630])
            with patch.object(C,'detect_star',return_value=None) as detect:
                C.clean_flow_star(Image.new('RGB',(512,512)))
                detect.assert_called_once()

    def test_left_corner_does_not_train_right_corner_profile(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(C,'FLOW_STAR_PROFILES',Path(tmp)/'profiles.json'):
            with patch.object(C,'detect_star',return_value={'x':40,'y':648,'size':48}):
                C.clean_flow_star(Image.new('RGB',(768,768)))
            self.assertFalse(C.FLOW_STAR_PROFILES.exists())

    def test_invalid_saved_region_falls_back_to_detection(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(C,'FLOW_STAR_PROFILES',Path(tmp)/'profiles.json'):
            C.atomic_json(C.FLOW_STAR_PROFILES,{'768x768':{'x':760,'y':760,'size':48}})
            with patch.object(C,'detect_star',return_value=None) as detect:
                _,report=C.clean_flow_star(Image.new('RGB',(768,768)))
            detect.assert_called_once();self.assertEqual(report['status'],'no_confident_match')
