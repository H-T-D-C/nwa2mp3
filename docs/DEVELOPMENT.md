# 開発・ビルドガイド

## 構成

- `nwa_gui.py`: 日本語GUI
- `nwa_conversion.py`: NWA探索、出力マッピング、変換とCLI
- `nwa_to_mp3.py`: CLI互換用の起動ファイル
- `tool_setup.py`, `resources/tool_catalog.json`: 外部ツール取得と固定版情報
- `app_paths.py`: 実行環境とユーザー設定パス
- `tests/`: unittestの回帰テスト
- `packaging/`, `scripts/`: Windowsアプリのビルド
- `docs/`: 利用者向けセットアップと開発資料

## ソースから起動する

Python 3.11以降と、GUI利用時はTkサポートが必要です。実行ファイルを用意できていなければ、GUIのセットアップ機能または`docs/SETUP.md`を参照してください。

```powershell
python .\nwa_gui.py
python .\nwa_to_mp3.py .\input --format flac
python -m unittest discover -s tests -v
```

## Windows配布ZIPを作る

現在のWindows x64配布版はPython 3.14.7とPyInstaller 6.22.3でビルドしています。リリースビルド用の依存バージョンは`requirements-build.txt`に固定しています。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_release.ps1
```

成果物は`dist\Nwa2Mp3-Windows-x64.zip`です。これにはアプリ、Python/Tcl/Tkランタイム、および`LICENSES/`と`THIRD_PARTY_NOTICES.md`を含めます。FFmpegとvgmstreamは含まず、初回セットアップ時に各自の利用環境へ取得します。

## 公開前に確認する

リポジトリ内のアプリケーションコードにはMIT Licenseを適用します。Python、Tcl/Tk、PyInstaller、取得ツールには別の条件があるため、ライセンス一覧と同梱文書も更新してください。`BGM00.nwa`はゲーム音声のサンプルで、MIT Licenseの対象ではありません。公開配布物やリリース素材へ含めないでください。
