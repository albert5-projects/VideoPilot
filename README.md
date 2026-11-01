# VideoPilot

VideoPilot is a Windows desktop tool for turning a video idea into an editable
CapCut or Kdenlive project. It connects script planning, local narration, Google
Flow images, captions, and editing. Review and final export happen in your editor.

## Workflow

1. Enter your idea, story instructions, duration, visual style, and image hold range.
2. Optionally upload a sample script and enter constant text for every image prompt.
3. Codex creates narration and scene visuals. Review the script before continuing.
4. Generate narration with Kokoro or an optional Chatterbox Nano reference voice.
5. Submit the image queue in Google Flow, then use **Recover generated images**
   to import results. Recovery supports normal and reverse navigation with saved progress.
6. Build with preset editing rules or Codex-directed editing decisions. Optional
   Remotion graphics illustrate suitable scenes.
7. Open the draft in your editor, review it, make final adjustments, and export.

Completed assets are cached so interrupted work can resume. Actual narration
length drives shot timing. Caption timing is approximate and should be reviewed.

## Requirements

- Windows, Python 3.11 or 3.12 with the Python launcher and Tkinter.
- Codex CLI installed and signed in, with access to a suitable model.
- Chrome or Edge and access to Google Flow for the image workflow.
- FFmpeg/FFprobe available on PATH for compressed audio and sample imports.
- CapCut 2.1.0 with a compatible plain native sample draft, or Kdenlive.
- Optional: an existing Remotion installation for motion graphics.

Local narration runs on CPU. Chatterbox requires more memory and disk space than
Kokoro. Codex, Google Flow, and optional services have their own access requirements,
subscription costs, and usage limits; installing VideoPilot does not include them.

## Setup

1. Run `Setup.bat` to create the main Python environment and install dependencies.
2. Run `Download_Models.bat` to download the Kokoro model and voices.
3. Run `Launch.bat` (or `Launch.vbs`) to open VideoPilot.
4. Follow [the Flow setup guide](FLOW_SETUP.html) to sign in through the dedicated
   browser profile. Never add your browser profile or login state to this repository.
5. For optional voice cloning, run `Install_Chatterbox_Nano.bat` and read
   [the Chatterbox Nano guide](CHATTERBOX_NANO.md). Setup installs a separate
   environment, downloads the model, and tests CPU generation.

CapCut installation uses a new empty destination project while CapCut is closed.
Keep the VideoPilot project media folder after handing a draft to an editor.
Use an editing revision when changing an already installed project.

## Repository contents and local data

This repository contains application source, tests, browser extension source,
setup/launch scripts, and documentation. The `.gitignore` deliberately allows only
reviewed distribution paths and file types; review it when adding new source files.

Python environments, model weights, generated audio/images/videos, projects,
verification outputs, credentials, and browser sessions are excluded. Normal app
data is stored under `%LOCALAPPDATA%\VideoPilot`, outside this repository.
Recreate environments and download models after cloning; local projects and
voice samples are not included in Git.

Before committing, inspect `git status --short` and `git diff --cached`.
Ignore rules do not remove files that were previously committed or explicitly
force-added. Keep account credentials and voice samples out of Git history.

## Development

Run `Run_Tests.bat` for the test commands supplied with the project.
The Python application lives in `videopilot/`; tests are in `tests/`.
See [sources](docs/SOURCES.md) and [verification notes](docs/VERIFICATION.md)
for supporting documentation. Some checks require local browser or editor tools.

## License

See [LICENSE](LICENSE). Dependencies, downloaded models, and services retain their
own licenses and terms.
