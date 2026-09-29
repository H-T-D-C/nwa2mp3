# Repository Guidelines

## Project Structure & Module Organization

This repository is in the planning stage. `PLAN.md` defines a Windows-first NWA-to-MP3 batch converter; `BGM00.nwa` is the existing audio fixture. Read the plan before implementing changes and preserve the fixture unchanged.

The planned layout places CLI orchestration in root-level `nwa_to_mp3.py`, usage instructions in `README.md`, and automated tests in `tests/test_nwa_to_mp3.py`. Optional external executables and their required DLLs belong in `tools/`. Default conversion output belongs in `mp3/`.

## Build, Test, and Development Commands

Target Python 3.11+ using only the standard library. Conversion requires `vgmstream-cli` and FFmpeg with `libmp3lame`. No build system, dependency manifest, or runnable converter currently exists.

After implementing the planned files, use:

```powershell
python .\nwa_to_mp3.py .\BGM00.nwa
python .\nwa_to_mp3.py .\input --recursive --dry-run
python -m unittest discover -s tests -v
git diff --check
```

These commands convert the sample, preview recursive output mappings, run the recommended standard-library test suite, and check patch whitespace, respectively.

## Coding Style & Naming Conventions

Use four-space indentation and PEP 8 conventions: `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Prefer `pathlib.Path`, `argparse`, and small functions separating discovery, output mapping, and conversion. Pass external commands as argument lists to `subprocess` without invoking a shell. No formatter or linter is configured.

## Testing Guidelines

No tests or coverage threshold exist yet. Use `unittest`, name modules `test_*.py`, and name cases `test_<behavior>`. Cover recursive mappings, case-insensitive extensions, output collisions, overwrite protection, failure continuation, and dry-run side effects. Mock subprocess failures and isolate generated files in temporary directories.

For integration checks, convert `BGM00.nwa` and inspect output with `ffprobe`; expect stereo, 44.1 kHz, and approximately 98.46 seconds. Document compressed-NWA validation separately.

## Commit & Pull Request Guidelines

The only existing commit is `add test files`; no formal convention is established. Use concise, imperative subjects and focused commits. PR descriptions should explain behavior changes, reference relevant plan sections or issues, and report commands run, results, and remaining validation gaps. Update usage documentation when CLI behavior changes.

## File Safety & Configuration

Preserve source NWA files and existing MP3s on failure. Finalize output only after successful validation. Keep generated audio, temporary files, and downloaded tool binaries out of commits. Resolve tools through explicit CLI paths, then `tools/`, then `PATH`, as specified in the plan.
