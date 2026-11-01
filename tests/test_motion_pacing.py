import unittest
from videopilot.core import Settings
from videopilot.editing import gentle_camera


class MotionPacingTests(unittest.TestCase):
    def speed(self,keys,seconds,axis):
        return max(abs(b[axis]-a[axis])/((b['at']-a['at'])*seconds) for a,b in zip(keys,keys[1:]))

    def test_duration_does_not_change_movement_speed(self):
        for style,axis in [('slow_zoom','scale'),('pan','x'),('float','y')]:
            speeds=[]
            for seconds in (.5,3,5,8,12,20,45,120):
                keys=gentle_camera({'duration':seconds*1e6},Settings(motion_style=style))
                speeds.append(self.speed(keys,seconds,axis))
                self.assertEqual(keys[0]['at'],0);self.assertEqual(keys[-1]['at'],1)
                self.assertTrue(all(a['at']<b['at'] for a,b in zip(keys,keys[1:])))
                for k in keys:
                    self.assertLessEqual(k['scale'],1.25)
                    self.assertLessEqual(abs(k['x']),(k['scale']-1)/2)
                    self.assertLessEqual(abs(k['y']),(k['scale']-1)/2)
            self.assertLess(max(speeds)-min(speeds),1e-10)

    def test_cuts_ease_and_long_shots_remain_bounded(self):
        for seconds in (5,8,120):
            keys=gentle_camera({'duration':seconds*1e6},Settings())
            peak=self.speed(keys,seconds,'scale')
            for a,b in (keys[:2],keys[-2:]):
                speed=abs(b['scale']-a['scale'])/((b['at']-a['at'])*seconds)
                self.assertLess(speed,peak*.3)

    def test_disabled_motion_stays_static(self):
        keys=gentle_camera({'duration':120000000},Settings(image_motion=False))
        self.assertEqual([k['scale'] for k in keys],[1.,1.])
