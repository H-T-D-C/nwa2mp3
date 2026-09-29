# NWA音声変換

VisualArt's／RealLive形式の`.nwa`音声をMP3・WAV・FLACへ変換するWindows用ツールです。配布版はPython不要です。変換に必要なFFmpegとvgmstreamは、手動または画面内の自動ダウンロードで準備します。

## はじめて使う

1. 配布ZIPを右クリックして「すべて展開」し、展開先の`Nwa2Mp3.exe`を起動します。アプリのファイルは一部だけ移動せず、フォルダーごと保管してください。
2. 初回セットアップ画面の「セットアップガイド」に沿ってFFmpegとvgmstreamを準備します。「必要なツールをまとめて導入」で自動ダウンロードする方法も選べます。
3. 「NWAファイル」または「フォルダー」を選び、出力形式・保存先を指定して「変換開始」を押します。フォルダー内をまとめて変換するときは「サブフォルダーも含める」を選びます。
4. MP3では音質プリセットを選べます。WAVとFLACは元のPCM音声を無劣化で保存します。完了後、「保存先を開く」でファイルを確認します。

既存の出力ファイルは初期設定では保護されます。置き換えたいときは上書きを明示してください。変換に失敗したファイルは理由をログに表示し、ほかのファイルの処理は続きます。プレビューで変換対象と出力先を開始前に確認できます。

## ツールを手動で導入する

FFmpegはターミナルで次の1行を実行して導入できます。

```powershell
winget install --id Gyan.FFmpeg --exact --source winget
```

導入後はアプリを起動し直してください。vgmstreamの取得・配置や検出できない場合の対処は[セットアップガイド](docs/SETUP.md)を参照してください。セットアップ画面から既存の`vgmstream-cli.exe`／`ffmpeg.exe`を指定する方法や、対応版ZIPを取り込む方法も利用できます。配布元とライセンス情報は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)にまとめています。

## コマンドラインで使う

Python 3.11以降を用意した開発環境では、同じ変換処理をCLIから使えます。外部ツールを未導入ならGUIからセットアップするか、`--vgmstream`と`--ffmpeg`で実行ファイルを指定してください。

```powershell
py -3 .\nwa_to_mp3.py .\BGM00.nwa
py -3 .\nwa_to_mp3.py .\input --recursive --dry-run
py -3 .\nwa_to_mp3.py .\input --output .\converted --bitrate 192k
py -3 .\nwa_to_mp3.py .\input --format flac
py -3 .\nwa_to_mp3.py .\input --format wav
python -m unittest discover -s tests -v
```

`--format`は`mp3`（既定）、`wav`、`flac`を選べます。MP3の音質・ビットレート設定はMP3出力時のみ使えます。出力先を省略すると、入力の隣に形式名のフォルダー（`mp3/`、`wav/`、`flac/`）を作成します。再帰変換時はサブフォルダー構成を保ちます。詳細な開発・ビルド手順は[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)を参照してください。

## 対応範囲と確認状況

`.nwa`と`.NWA`を扱います。MP3はVBR品質または固定ビットレート、WAVとFLACは無劣化で出力できます。GUIの形式選択とエラー表示、両ツールの取得・検証・導入を確認済みです。圧縮NWAの実ファイル検証は未実施です。
