"""Typed inference inputs for the pinned kokoro-onnx 0.4.9 backend.

That backend hardcodes int32 speed for exports named `input_ids`, even
when the model declares float32. Build inputs from model metadata instead,
before the fractional playback speed can be truncated to an integer.
Tokenization, voice lookup, splitting and silence trimming remain upstream.
"""
import math
import numpy as np
from kokoro_onnx import Kokoro
from kokoro_onnx.config import MAX_PHONEME_LENGTH, SAMPLE_RATE


class TypedKokoro(Kokoro):
    def _create_audio(self, phonemes, voice, speed):
        if len(phonemes) > MAX_PHONEME_LENGTH:
            raise ValueError('Narration beat is too long. Split it into shorter sentences.')
        speed = float(speed)
        if not math.isfinite(speed) or not .5 <= speed <= 2.0:
            raise ValueError('Voice speed must be a finite number between 0.5 and 2.0.')
        tokens = self.tokenizer.tokenize(phonemes)
        if len(tokens) > MAX_PHONEME_LENGTH:
            raise ValueError('Too many narration tokens. Split this beat into shorter sentences.')
        metadata = {item.name: item for item in self.sess.get_inputs()}
        token_name = 'input_ids' if 'input_ids' in metadata else 'tokens'
        if set(metadata) != {token_name, 'style', 'speed'}:
            raise ValueError('Unsupported Kokoro model inputs. Use the bundled model downloader.')
        values = {token_name: [[0, *tokens, 0]], 'style': voice[len(tokens)], 'speed': [speed]}
        dtypes = {'tensor(float)': np.float32, 'tensor(double)': np.float64,
                  'tensor(float16)': np.float16, 'tensor(int64)': np.int64,
                  'tensor(int32)': np.int32}
        inputs = {}
        for name, value in values.items():
            dtype = dtypes.get(metadata[name].type)
            if dtype is None:
                raise ValueError(f'Unsupported Kokoro input type for {name}: {metadata[name].type}')
            # Never silently truncate 0.95 to zero, or 1.15 to one.
            if name == 'speed' and np.issubdtype(dtype, np.integer) and not speed.is_integer():
                raise ValueError('This Kokoro export cannot use fractional voice speed. Use the bundled model downloader.')
            inputs[name] = np.asarray(value, dtype=dtype)
        return self.sess.run(None, inputs)[0], SAMPLE_RATE
