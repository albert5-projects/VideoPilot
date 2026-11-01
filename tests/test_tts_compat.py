"""Regression tests use the real pinned Kokoro wrapper and strict input checks."""
import unittest
from types import SimpleNamespace
import numpy as np
from videopilot.kokoro_compat import TypedKokoro
from kokoro_onnx import Kokoro


class StrictSession:
    def __init__(self, name='input_ids', speed_type='tensor(float)'):
        self.name = name
        self.inputs = [SimpleNamespace(name=name, type='tensor(int64)'),
                       SimpleNamespace(name='style', type='tensor(float)'),
                       SimpleNamespace(name='speed', type=speed_type)]
        self.calls = []
    def get_inputs(self):
        return self.inputs
    def run(self, _, inputs):
        if inputs['speed'].dtype != np.float32:
            raise ValueError('Unexpected input data type. Actual: tensor(int32), expected: tensor(float)')
        if inputs[self.name].dtype != np.int64:
            raise ValueError('Tokens must be int64')
        if inputs['style'].dtype != np.float32:
            raise ValueError('Style must be float32')
        self.calls.append(inputs)
        return [np.ones(2400, dtype=np.float32)]


def engine(cls=TypedKokoro, name='input_ids'):
    instance = cls.__new__(cls)
    instance.sess = StrictSession(name)
    instance.tokenizer = SimpleNamespace(tokenize=lambda _: [4, 8, 12])
    instance.voices = {'am_michael': np.ones((510, 1, 256), dtype=np.float64)}
    return instance


class KokoroCompatibilityTests(unittest.TestCase):
    def test_upstream_reproduces_reported_error(self):
        original = engine(Kokoro)
        with self.assertRaisesRegex(ValueError, r'tensor\(int32\)'):
            original.create('hello', voice='am_michael', speed=1.0, is_phonemes=True, trim=False)

    def test_current_and_legacy_models_preserve_fractional_speed(self):
        for name in ('input_ids', 'tokens'):
            for speed in (1, .8, .95, 1.0, 1.15, 1.2):
                with self.subTest(name=name, speed=speed):
                    fixed = engine(name=name)
                    samples, rate = fixed.create('hello', voice='am_michael', speed=speed, is_phonemes=True, trim=False)
                    self.assertEqual(rate, 24000)
                    self.assertEqual(samples.size, 2400)
                    values = fixed.sess.calls[0]
                    self.assertAlmostEqual(float(values['speed'][0]), speed, places=6)
                    self.assertEqual(values[name].tolist(), [[0, 4, 8, 12, 0]])
                    self.assertEqual(values['style'].shape, (1, 256))

    def test_integer_speed_export_never_silently_truncates(self):
        fixed = engine()
        fixed.sess.inputs[-1].type = 'tensor(int32)'
        with self.assertRaisesRegex(ValueError, 'fractional'):
            fixed.create('hello', voice='am_michael', speed=.95, is_phonemes=True, trim=False)
        self.assertEqual(fixed.sess.calls, [])

    def test_long_phonemes_are_not_silently_cut(self):
        fixed = engine()
        with self.assertRaisesRegex(ValueError, 'too long'):
            fixed._create_audio('a' * 600, fixed.voices['am_michael'], 1.0)
