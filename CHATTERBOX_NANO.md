# Optional Chatterbox Nano narration

Run `Install_Chatterbox_Nano.bat` with internet access. It installs CPU PyTorch
and the official Chatterbox source in `.venv-chatterbox`, downloads Nano into
`models/chatterbox-cache`, and tests generation using a synthetic Kokoro
reference. The existing `.venv` and Kokoro models are not modified. Git must
be installed because upstream includes a Git dependency. Setup can require
several GB of disk space. Keep other heavy applications closed during testing
on a PC with 8 GB RAM.

Setup reports elapsed generation time and saves a test WAV for listening.
Nano is marked ready only after generation succeeds. A passing test verifies
local execution; listen to previews to judge pronunciation and voice similarity.
Package versions are recorded in `models/chatterbox-cache/installed-packages.txt`.

In **1. Video**, click **Nano voices**, upload an audio sample,
name it, and choose **Use selected voice**. Use 10–15 seconds of clear English
speech from one speaker. WAV, MP3, FLAC and M4A are accepted through FFmpeg.
Long samples use their first 15 seconds; samples of 5 seconds or less are rejected.
The narrator dropdown contains both Kokoro voices and saved Nano voices.
**Preview voice** (six seconds) previews the selected narrator.

Nano uses the saved sample as its voice reference; no separate training is
needed. Samples stay local under `%LOCALAPPDATA%\VideoPilot\cloned-voices`.
Each new project stores its reference, so removing a library entry does not
break existing projects. Existing projects retain their saved narrator.
Inference runs in a separate CPU worker with two threads and offline model
loading. The existing narration speed control is applied with pitch-preserving
time stretching for Nano. Narration caching and downstream editing are unchanged.

Official implementation: https://github.com/resemble-ai/chatterbox
