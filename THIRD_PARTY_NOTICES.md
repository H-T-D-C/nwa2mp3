# Third-party software notices

The app can obtain these separate command-line tools on the user's request. They are stored under the current Windows user's `%LOCALAPPDATA%\Nwa2Mp3\tools\` directory and are not included in the application ZIP.

| Tool | Pinned version | Download source | Licence/source information |
|---|---:|---|---|
| vgmstream command-line build | r2117 | [Official release](https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip) | [vgmstream COPYING](https://github.com/vgmstream/vgmstream/blob/master/COPYING) |
| FFmpeg essentials | 9.0.2 | [Gyan Windows build](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip) | [Build details, included libraries and source links](https://www.gyan.dev/ffmpeg/builds/) |

The app verifies each archive's SHA-256 against the pinned values in `resources/tool_catalog.json` before extracting it. FFmpeg's essentials build includes `libmp3lame`. See the linked project and build pages for the terms that apply to each separate tool.

The Python application uses the Python standard library. The Windows bundle is built with PyInstaller; its build-time dependency and licence notice will be recorded alongside the release build configuration.
