# Verification — VideoPilot 0.2.1

## 0.2.1 patch validation — 23 October 2026

26 Python tests pass, including four new regression tests using the pinned
kokoro-onnx 0.4.9 package. The unpatched wrapper reproduces the integer/float
error against a strict session double; the patched wrapper supplies metadata-typed
inputs for both input_ids and tokens exports. Fractional speeds are preserved.

Real CPU inference also ran with the exact model and voice files fetched by
Download_Models.bat. A Michael narration beat produced valid 24 kHz PCM WAVs
at 1.0x (4.879 s), 0.95x (5.199 s) and 1.15x (4.495 s).
This was a Linux Python 3.12 run, not a Windows laptop performance test.

The GUI was launched on an isolated X display and its form, open dropdown,
settings, disabled controls and error dialog were visually inspected.
Native Windows title-bar appearance remains unverified. System file dialogs
continue to use Windows styling. The patch changes no Flow helper code.

The remaining Flow/CapCut integration limitations below still apply.

## Prior 0.2 validation

23 October 2026. **22 Python tests and 4 Node tests pass.** Python compilation and JavaScript syntax checks pass.

The new tests cover queue isolation when prompts/settings change, completed-download receipts, rejection of incomplete/corrupt/small images, path traversal rejection, variant selection, protection of installed-project assets and Flow resume without rerunning TTS. A deterministic integration test reaches a completed draft from a Flow queue using synthetic images and mocked narration. The Node tests check Flow-only page scope, image-host restrictions, safe filenames, queue validation and rejection of small/wrong-aspect previews.

The earlier tests still cover measured timing, continuous image/caption coverage, PCM concatenation, reference remapping, template preservation, refusal to overwrite nonempty CapCut projects, install/restore protection, completion gates, cancellation and bounded duration revision. The earlier backup-name collision fix remains included.

## What has not been run here

- The helper against the real authenticated Google Flow page or your Google AI Plus account.
- Real Chrome/Edge extension loading, prompt filling, result detection or downloads. Browser-specific behavior remains unverified. The pure extension logic was tested; that is not an end-to-end browser test.
- Native Windows Tkinter rendering, Windows Known Folder API or your laptop's performance.
- Actual Codex generation and Kokoro inference on your PC (local Linux Kokoro inference was added in 0.2.1).
- Actual CapCut 2.1.0 loading/playback. Adapter tests use a synthetic draft fixture; a user-native sample is still needed.
- Semantic quality of images, narration, factual claims or YouTube performance.

No Windows GUI session or authenticated Flow browser was used. No login credentials were read or requested, and no cloud generation or paid request was sent during this update.

## First local acceptance test

Use a 30-second English project with one Flow output per prompt. Confirm that:

1. Codex reuses your existing login and produces a script.
2. Local narration is audible and its measured duration is close to target.
3. The Flow helper can select your actual input/Generate controls, generate one shot, detect its output and save it with a completed receipt.
4. VideoPilot imports that image and, after the remaining shots, builds a draft.
5. A native CapCut 2.1.0 sample is accepted and the installed timeline opens correctly in a new empty project.
6. You can review and save the edit without rendering.

If Flow exposes only small previews or incompatible editor behavior, use native downloads/manual imports until that specific UI can be adapted. No hidden endpoints or authentication workarounds are included.
# Flow import repair — 2026-10-29

The Python suite passed (156 tests); after the final gallery retry and background-import changes, all 74 Flow tests passed again. Chromium card tests cover exact prompt fields, shared prompt prefixes, ambiguous history steps, and duplicate prompts. Regression tests cover advancing beyond unrelated gallery assets, history loading grace, nested response ownership, legacy receipts, and changed receipt bytes.

Both `python -m verification.check_flow_recovery` and `python -m verification.check_flow_identity` passed against local Chromium fixtures. The nine-shot fixture deliberately seeds incorrect images **and incorrect saved result URLs**, then verifies all nine repaired files, including three transient read failures. Recovery sends zero generation clicks. Live signed-in Google Flow was not tested for this change.


## Image overlay update � 2026-10-29

The overlay geometry/timing validation tests and 12 editing tests passed. `python -m verification.check_overlays` renders a real two-second Remotion MP4 using a synthetic image and a supplied arrow plan; FFprobe verifies the output. The extracted frame `verification/overlay-preview.png` was visually checked: image fills the frame, label has no panel, and arrow targets the image landmark under the shared camera transform. This verifies rendering with fixture decisions, not live Codex visual localization or anatomical accuracy. Per-shot Codex plans remain reviewable under `overlay-plans`.
