# Repository Guidelines

## Project Structure & Module Organization

This is a Windows-first VisualArt's/RealLive NWA converter. `nwa_gui.py` contains the Tk interface, `nwa_conversion.py` implements shared discovery and conversion, and `nwa_to_mp3.py` is the CLI entry point. Tool setup and the pinned download catalog are in `tool_setup.py` and `resources/`. Build definitions live in `packaging/` and `scripts/`; end-user and developer documentation is in `README.md` and `docs/`.

`BGM00.nwa` is an existing game-audio fixture. Preserve the file unchanged and never include it in the MIT license grant or public release assets without separate distribution rights.

## Build, Test, and Development Commands

Python 3.11+ and Tk are needed to run from source. Use Python 3.14.7 x64 for the current reproducible Windows release build.

```powershell
python .\nwa_gui.py
python .\nwa_to_mp3.py .\input --format flac
python -m unittest discover -s tests -v
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_release.ps1
git diff --check
```

The release command creates `dist\Nwa2Mp3-Windows-x64.zip`. Do not commit `dist/`, `build/`, generated audio, or downloaded tools.

## Coding Style & Naming Conventions

Use four spaces and PEP 8 names (`snake_case`, `PascalCase`, `UPPER_SNAKE_CASE`). Keep GUI work on Tk's main thread; background tasks report events through the queue. Use `pathlib`, argument-list `subprocess` calls, and no shell invocation for conversion tools. MP3 quality controls apply only to MP3; WAV remains PCM and FLAC is lossless.

## Testing Guidelines

Tests use `unittest` under `tests/test_*.py`; name cases `test_<behavior>`. Cover output mappings for MP3/WAV/FLAC, collisions, overwrite protection, failed conversions, tool setup validation, and GUI progress/error event handling. Use temporary directories and mock external processes. For real audio checks, confirm codec, channels, sample rate, and duration with `ffprobe`.

## Commits, Licensing, and Release Notes

Use concise imperative commit subjects. Keep README instructions aligned with GUI and CLI behavior, and report validation and known gaps in release notes. Application code uses the root MIT `LICENSE`; Python/Tcl/Tk and external conversion tools retain their separate terms. Update `THIRD_PARTY_NOTICES.md` and the `LICENSES/` files when bundled dependencies change. Never describe the game-audio fixture as MIT-licensed.
