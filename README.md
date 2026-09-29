# NWA音声変換

VisualArt's／RealLive形式の`.nwa`音声を、MP3・WAV・FLACへ変換するWindows用ツールです。ファイル単体またはフォルダーをGUIで選び、一括変換できます。Windows x64向け配布版にはPython実行環境が含まれます。

## 主な機能

- MP3はVBR音質または固定ビットレート、WAVはPCM、FLACは可逆圧縮で出力
- サブフォルダーを含む一括変換、開始前の出力プレビュー、進捗確認と中止
- 既存ファイルを標準で保護し、失敗したファイルの理由をログへ記録
- FFmpegとvgmstreamの手動セットアップガイドと任意の自動導入

## はじめて使う

1. 配布ZIPを展開し、フォルダー内の`Nwa2Mp3.exe`を起動します。
2. 「セットアップガイド」に沿ってFFmpegとvgmstreamを用意します。FFmpegはターミナルで `winget install --id Gyan.FFmpeg --exact --source winget` を実行して導入できます。アプリ内の自動ダウンロードも選べます。
3. NWAファイルまたはフォルダー、出力形式、保存先を選び「変換開始」を押します。出力先を指定しなければ、入力の隣に形式名のフォルダーを作成します。
4. 完了したら「保存先を開く」を押します。

詳しい導入手順は[セットアップガイド](docs/SETUP.md)を参照してください。

## CLI

Python 3.11以降の開発環境では、コマンドラインからも実行できます。

```powershell
py -3 .\nwa_to_mp3.py .\BGM00.nwa
py -3 .\nwa_to_mp3.py .\input --recursive --dry-run
py -3 .\nwa_to_mp3.py .\input --format wav
py -3 .\nwa_to_mp3.py .\input --format flac
py -3 .\nwa_to_mp3.py .\input --output .\converted --bitrate 192k
```

`--format`は`mp3`（既定）、`wav`、`flac`です。音質・ビットレート指定はMP3のみで使えます。出力先を指定しない場合は、入力の隣に`mp3/`、`wav/`、または`flac/`を作り、再帰変換では相対パスを保ちます。

## ライセンスと配布ソフト

このリポジトリのアプリケーションコードは[MIT License](LICENSE)で提供します。Windows配布版に含まれるPythonとTcl/Tk、およびPyInstallerの実行部品には個別のライセンスがあり、`LICENSES/`にライセンス文書、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)に一覧を置いています。FFmpegとvgmstreamは配布ZIPに含めず、アプリから導入を選んだ場合に各配布元から取得します。これらはMIT Licenseの対象ではありません。

ゲーム音声ファイルなど第三者が権利を持つデータには、このMIT Licenseは適用されません。公開時はライセンスと配布条件を個別に確認してください。

## 開発

起動、ビルド、リポジトリ構成は[開発ガイド](docs/DEVELOPMENT.md)を参照してください。
