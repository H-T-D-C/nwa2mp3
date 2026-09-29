# Third-Party Software Notices

The repository's own application code is licensed under the MIT License in `LICENSE`. This notice covers third-party components in the Windows application bundle and tools the application can download separately. The MIT License does not replace any of their terms.

## Included in the Windows application bundle

| Component | Version in current build | License | License text |
|---|---:|---|---|
| Python runtime | 3.14.7 | Python Software Foundation License 2 | [`LICENSES/Python-PSF-2.0.txt`](LICENSES/Python-PSF-2.0.txt) |
| Tcl/Tk runtime | 9.0 | Tcl/Tk license terms | [`LICENSES/TclTk-license.terms`](LICENSES/TclTk-license.terms) |
| PyInstaller bootloader and runtime hooks | 6.22.3 | GPL 2.0 or later with the PyInstaller Bootloader Exception; applicable runtime hooks use Apache 2.0 | [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt), [PyInstaller license details](https://pyinstaller.org/en/stable/license.html), [PyInstaller license file](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt) |

PyInstaller's exception permits distributing the application bundle under its own license, subject to the licenses of the bundled dependencies. This repository does not modify PyInstaller.

## Optional tools downloaded by the user

These tools are not included in the application ZIP. When a user selects automatic setup, the app fetches the pinned archive from its listed publisher, verifies the SHA-256 from `resources/tool_catalog.json`, and keeps the archive's extracted files, including upstream license files, under that user's `%LOCALAPPDATA%` directory.

| Tool | Pinned version | Publisher and license | Source and terms |
|---|---:|---|---|
| vgmstream command-line build | r2117 | vgmstream contributors; permissive license in the project's `COPYING` file | [Pinned Windows archive](https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip), [COPYING](https://github.com/vgmstream/vgmstream/blob/master/COPYING) |
| FFmpeg essentials build | 9.0.2 | Gyan Windows build; GPLv3 build with separately licensed libraries | [Pinned ZIP](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip), [build details and source links](https://www.gyan.dev/ffmpeg/builds/) |

The vgmstream and FFmpeg binaries and their dependencies remain under their respective upstream licenses. Review the license files in each downloaded package before redistributing that package. The FFmpeg essentials build contains `libmp3lame` for MP3 output.

## Build-only tools

PyInstaller and its Python package dependencies in `requirements-build.txt` are used only to produce the Windows bundle. They are not installed separately for end users. PyInstaller's terms and exception are linked above.
