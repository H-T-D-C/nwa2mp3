# 開発者向け起動・配布手順

## GUIとCLIの起動

WindowsにPython 3.11以降が必要です。ソースから起動するときは、リポジトリのルートで次を実行します。

```powershell
python .\nwa_gui.py
python .\nwa_to_mp3.py --help
python -m unittest discover -s tests -v
```

## 配布ZIPを作る

Pythonを個別にインストールする必要があるのは、配布ZIPを作る開発者だけです。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_release.ps1
```

Windows x64上でビルドします。作成される`dist\Nwa2Mp3-Windows-x64.zip`を展開すると`Nwa2Mp3.exe`が使えます。初回導入で取得したFFmpegやvgmstreamは配布ZIPに含まれず、利用者ごとに`%LOCALAPPDATA%\Nwa2Mp3\tools\`へ保存します。
