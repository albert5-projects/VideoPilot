"""Loaded only in the isolated Chatterbox worker process."""
from .core import atomic_json, fingerprint, file_hash
from .tts_progress import write_progress


def narration_signature(text, reference_hash, speed):
    return fingerprint(['chatterbox-nano-v1', text, reference_hash, speed])


class NanoVoice:
    def __init__(self, request, progress):
        import torch
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        write_progress(progress, {'message': 'Loading local Chatterbox Nano voice model...'})
        self.model = ChatterboxTurboTTS.from_pretrained(device='cpu', nano=True)
        self.model.prepare_conditionals(request['reference'])
        self.request = request
        self.reference_hash = file_hash(request['reference'])

    def signature(self, text):
        return narration_signature(text, self.reference_hash, self.request['speed'])

    def create(self, text, voice, speed, lang):
        import numpy as np
        import torch
        with torch.inference_mode():
            samples = self.model.generate(text).squeeze().cpu().numpy()
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if speed != 1.:
            import librosa
            samples = librosa.effects.time_stretch(samples, rate=speed)
        return samples, self.model.sr
