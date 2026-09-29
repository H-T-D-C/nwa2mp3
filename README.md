# NWA to MP3

Windows向けのVisualArt's／RealLive形式 `.nwa` 音声一括変換ツールです。Python 3.11以降、[vgmstream-cli](https://vgmstream.org/)、`libmp3lame` 対応の[FFmpeg](https://ffmpeg.org/download.html)が必要です。外部ツールは自動でダウンロード・インストールしません。

## セットアップ

Pythonをインストールし、vgmstream-cliとFFmpegを入手してPATHへ追加するか、各実行ファイルと配布物に同梱のDLLを`tools/`へ配置してください。ツールは「CLIで指定したパス → `tools/` → PATH」の順で探します。配置を個別に指定する例:

```powershell
py -3 .\nwa_to_mp3.py .\BGM00.nwa --vgmstream .\tools\vgmstream-cli.exe --ffmpeg .\tools\ffmpeg.exe
```

## 使用例

```powershell
# 1ファイルを既定品質(VBR 2)で変換し、隣のmp3フォルダーへ出力
py -3 .\nwa_to_mp3.py .\BGM00.nwa

# フォルダー直下を固定ビットレートで変換
py -3 .\nwa_to_mp3.py .\input --output .\converted --bitrate 192k

# 再帰的な出力予定を表示（ファイル変更や外部ツール実行なし）
py -3 .\nwa_to_mp3.py .\input --recursive --dry-run

# サブフォルダーを含め、既存MP3を置き換える
py -3 .\nwa_to_mp3.py .\input --recursive --overwrite --quality 0
```

入力が単一ファイルなら`mp3/`へ、フォルダーならその中の`mp3/`へ出力します。`--output`指定時はそこへ出力し、再帰検索では相対フォルダー構成を保ちます。`.nwa`/`.NWA`のどちらも対象です。既存出力は通常スキップし、ループを適用せず全体を一度だけ復号します。MP3非対応のチャンネル数・サンプルレートや、変換できなかったファイルは理由を表示して次のファイルを続けます。失敗が1件以上あれば終了コード1、処理開始時のエラーは2、中断は130です。

## 確認とテスト

```powershell
py -3 -m unittest discover -s tests -v
ffprobe -v error -show_entries stream=codec_name,channels,sample_rate -show_entries format=duration .\mp3\BGM00.mp3
```

リポジトリの`BGM00.nwa`は44.1 kHz、ステレオ、約98.46秒の非圧縮PCMサンプルです。圧縮NWAサンプルは同梱していないため、圧縮レベル0～5の実ファイル検証は未実施です。
