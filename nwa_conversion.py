#!/usr/bin/env python3
"""Batch-convert VisualArt's NWA audio to common audio formats."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app_paths import application_dir


SCRIPT_DIR = application_dir()
MP3_SAMPLE_RATES = {
    8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000,
}
OUTPUT_FORMATS = ("mp3", "wav", "flac")


class SetupError(Exception):
    """An error that prevents a conversion run from starting."""


class ConversionError(Exception):
    """A recoverable error converting one input file."""


class ConversionCancelled(Exception):
    """Raised after stopping the active child process and cleaning its files."""


ProgressCallback = Callable[[str, Path], None]


@dataclass(frozen=True)
class Job:
    source: Path
    output: Path


@dataclass
class Summary:
    success: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False


def discover_sources(source: Path, recursive: bool) -> list[Path]:
    if not source.exists():
        raise SetupError(f"入力が見つかりません: {source}")
    if source.is_file():
        if source.suffix.casefold() != ".nwa":
            raise SetupError(f"入力ファイルの拡張子は .nwa である必要があります: {source}")
        return [source.resolve()]
    if not source.is_dir():
        raise SetupError(f"入力はファイルまたはフォルダーを指定してください: {source}")
    iterator = source.rglob("*") if recursive else source.iterdir()
    files = sorted(
        (path.resolve() for path in iterator if path.is_file() and path.suffix.casefold() == ".nwa"),
        key=lambda path: str(path).casefold(),
    )
    if not files:
        raise SetupError(f"NWAファイルが見つかりません: {source}")
    return files


def build_jobs(
    sources: Sequence[Path], input_root: Path, output_root: Path,
    output_format: str = "mp3",
) -> list[Job]:
    if output_format not in OUTPUT_FORMATS:
        raise SetupError(f"未対応の出力形式です: {output_format}")
    jobs: list[Job] = []
    seen: dict[str, Path] = {}
    for source in sources:
        relative = source.relative_to(input_root) if input_root.is_dir() else Path(source.name)
        output = (output_root / relative).with_suffix(f".{output_format}").resolve()
        key = os.path.normcase(str(output))
        if key in seen:
            raise SetupError(f"出力名が衝突します: {seen[key]} と {source} → {output}")
        seen[key] = source
        jobs.append(Job(source, output))
    return jobs


def resolve_tool(explicit: str | None, name: str, configured: str | None = None) -> str:
    """Resolve an explicitly configured, bundled, or PATH executable."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise SetupError(f"指定されたツールが見つかりません: {candidate}")
        return str(candidate.resolve())
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_file():
            raise SetupError(f"設定したツールが見つかりません: {candidate}")
        return str(candidate.resolve())
    try:
        from app_paths import tools_dir

        managed_dir = tools_dir() / ("vgmstream" if name == "vgmstream-cli" else name)
        if managed_dir.is_dir():
            candidates = [
                *managed_dir.glob(f"*/{name}.exe"),
                *managed_dir.glob(f"*/bin/{name}.exe"),
            ]
            for candidate in sorted(candidates, reverse=True):
                if candidate.is_file():
                    return str(candidate.resolve())
        direct = managed_dir / (f"{name}.exe" if os.name == "nt" else name)
        if direct.is_file():
            return str(direct.resolve())
    except OSError:
        pass
    suffixes = (".exe", "") if os.name == "nt" else ("",)
    for suffix in suffixes:
        bundled = SCRIPT_DIR / "tools" / f"{name}{suffix}"
        if bundled.is_file():
            return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise SetupError(f"{name} が見つかりません。README.md の導入手順を確認してください。")


def run_process(
    command: Sequence[str], cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run without a shell, periodically checking GUI cancellation."""
    process = subprocess.Popen(
        list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        startupinfo=(subprocess.STARTUPINFO() if os.name == "nt" else None),
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    try:
        while True:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                raise ConversionCancelled("処理を中止しました")
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def check_process(command: Sequence[str], operation: str) -> subprocess.CompletedProcess[str]:
    try:
        result = run_process(command)
    except OSError as exc:
        raise SetupError(f"{operation}を実行できません: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "詳細情報なし").strip()
        raise SetupError(f"{operation}に失敗しました: {detail}")
    return result


def ensure_mp3_encoder(ffmpeg: str) -> None:
    result = check_process([ffmpeg, "-hide_banner", "-encoders"], "FFmpeg")
    if "libmp3lame" not in result.stdout + result.stderr:
        raise SetupError("FFmpegがlibmp3lameエンコーダーに対応していません。")


def ensure_ffmpeg(ffmpeg: str) -> None:
    result = check_process([ffmpeg, "-version"], "FFmpeg")
    if not result.stdout.casefold().lstrip().startswith("ffmpeg version"):
        raise SetupError("FFmpegの動作を確認できませんでした。")


def decode_and_validate(
    vgmstream: str, source: Path, wav_path: Path,
    cancel_event: threading.Event | None = None,
    output_format: str = "mp3",
) -> None:
    try:
        result = run_process([vgmstream, "-i", "-o", str(wav_path), str(source)], cancel_event)
    except OSError as exc:
        raise ConversionError(f"vgmstream-cliを実行できません: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "詳細情報なし").strip()
        raise ConversionError(f"NWAの復号に失敗しました: {detail}")
    if not wav_path.is_file():
        raise ConversionError("vgmstream-cliがWAVを作成しませんでした。")
    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            rate = wav_file.getframerate()
            width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            if wav_file.getcomptype() != "NONE":
                raise ConversionError("復号WAVが非圧縮PCMではありません。")
            if output_format == "mp3":
                if channels not in (1, 2):
                    raise ConversionError(f"MP3に対応しないチャンネル数です: {channels}")
                if rate not in MP3_SAMPLE_RATES:
                    raise ConversionError(f"MP3に対応しないサンプルレートです: {rate} Hz")
            if width not in (1, 2, 3, 4) or frame_count <= 0:
                raise ConversionError("復号WAVの音声形式またはフレーム数が不正です。")
            expected = frame_count * channels * width
            actual = 0
            while block := wav_file.readframes(65536):
                actual += len(block)
            if actual != expected:
                raise ConversionError(
                    f"復号WAVが不完全です（音声データ {actual} / {expected} bytes）。"
                )
    except (wave.Error, EOFError, OSError) as exc:
        raise ConversionError(f"復号WAVを読み取れません: {exc}") from exc


def convert_one(
    job: Job, vgmstream: str, ffmpeg: str, quality: int | None,
    bitrate: str | None, overwrite: bool,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    output_format: str = "mp3",
) -> None:
    temp_output: Path | None = None
    try:
        if output_format not in OUTPUT_FORMATS:
            raise ConversionError(f"未対応の出力形式です: {output_format}")
        job.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="nwa2mp3-") as temp_dir:
            wav_path = Path(temp_dir) / "decoded.wav"
            if cancel_event and cancel_event.is_set():
                raise ConversionCancelled("処理を中止しました")
            if progress:
                progress("復号中", job.source)
            decode_and_validate(vgmstream, job.source, wav_path, cancel_event, output_format)
            with tempfile.NamedTemporaryFile(
                prefix=f".{job.output.stem}.", suffix=f".tmp.{output_format}",
                dir=job.output.parent, delete=False,
            ) as temp_file:
                temp_output = Path(temp_file.name)
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(wav_path), "-map", "0:a:0", "-vn",
            ]
            if output_format == "mp3":
                command += ["-c:a", "libmp3lame"]
                command += ["-q:a", str(quality)] if quality is not None else ["-b:a", bitrate or "192k"]
            elif output_format == "wav":
                # vgmstream already produced PCM; stream-copy into the requested WAV container.
                command += ["-c:a", "copy"]
            else:
                command += ["-c:a", "flac"]
            command += ["-f", output_format, str(temp_output)]
            try:
                if progress:
                    progress(f"{output_format.upper()}作成中", job.source)
                result = run_process(command, cancel_event)
            except ConversionCancelled:
                raise
            except OSError as exc:
                raise ConversionError(f"FFmpegを実行できません: {exc}") from exc
            if result.returncode:
                detail = (result.stderr or result.stdout or "詳細情報なし").strip()
                raise ConversionError(f"{output_format.upper()}の作成に失敗しました: {detail}")
            if not temp_output.is_file() or temp_output.stat().st_size == 0:
                raise ConversionError(f"FFmpegが有効な{output_format.upper()}ファイルを作成しませんでした。")
            _validate_encoded_output(temp_output, output_format)
            if cancel_event and cancel_event.is_set():
                raise ConversionCancelled("処理を中止しました")
            if overwrite:
                os.replace(temp_output, job.output)
            else:
                # Windows rename fails if another process created the final name.
                os.rename(temp_output, job.output)
            temp_output = None
    except OSError as exc:
        raise ConversionError(f"ファイルを作成・置換できません: {exc}") from exc
    finally:
        if temp_output is not None:
            try:
                temp_output.unlink(missing_ok=True)
            except OSError:
                pass


def _validate_encoded_output(path: Path, output_format: str) -> None:
    if output_format == "flac":
        try:
            with path.open("rb") as stream:
                if stream.read(4) != b"fLaC":
                    raise ConversionError("FFmpegが有効なFLACファイルを作成しませんでした。")
        except OSError as exc:
            raise ConversionError(f"作成したFLACを確認できません: {exc}") from exc
    elif output_format == "wav":
        try:
            with wave.open(str(path), "rb") as wav_file:
                if wav_file.getcomptype() != "NONE" or wav_file.getnframes() <= 0:
                    raise ConversionError("FFmpegが有効なPCM WAVを作成しませんでした。")
                expected = wav_file.getnframes() * wav_file.getnchannels() * wav_file.getsampwidth()
                actual = sum(len(block) for block in iter(lambda: wav_file.readframes(65536), b""))
                if actual != expected:
                    raise ConversionError("作成したWAVの音声データが不完全です。")
        except (wave.Error, EOFError, OSError) as exc:
            raise ConversionError(f"作成したWAVを確認できません: {exc}") from exc


def convert_batch(
    jobs: Sequence[Job], vgmstream: str, ffmpeg: str, quality: int | None,
    bitrate: str | None, overwrite: bool,
    cancel_event: threading.Event | None = None,
    progress: Callable[[str, Path, int, int], None] | None = None,
    output_format: str = "mp3",
) -> Summary:
    summary = Summary()
    total = len(jobs)
    for index, job in enumerate(jobs, 1):
        if cancel_event and cancel_event.is_set():
            summary.cancelled = True
            break
        if job.output.exists() and not overwrite:
            summary.skipped += 1
            stage = "スキップ"
            if progress:
                progress(stage, job.source, index, total)
            continue
        if progress:
            progress("処理開始", job.source, index, total)
        try:
            file_progress = (
                lambda phase, source, i=index: progress(phase, source, i, total)
            ) if progress else None
            convert_one(
                job, vgmstream, ffmpeg, quality, bitrate, overwrite,
                cancel_event, file_progress, output_format,
            )
        except ConversionCancelled:
            summary.cancelled = True
            break
        except ConversionError as exc:
            summary.failed += 1
            if progress:
                progress(f"失敗: {exc}", job.source, index, total)
            continue
        summary.success += 1
        if progress:
            progress("完了", job.source, index, total)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VisualArt's / RealLive形式のNWA音声をMP3・WAV・FLACへ一括変換します。"
    )
    parser.add_argument("input", type=Path, help="NWAファイルまたは入力フォルダー")
    parser.add_argument("--output", type=Path, help="出力フォルダー（既定値: 入力隣の形式名フォルダー）")
    parser.add_argument("--recursive", action="store_true", help="サブフォルダーも検索")
    parser.add_argument(
        "--format", choices=OUTPUT_FORMATS, default="mp3",
        help="出力形式: mp3（既定）, wav, flac",
    )
    quality_group = parser.add_mutually_exclusive_group()
    quality_group.add_argument("--quality", type=int, choices=range(10),
                               help="VBR品質 0～9（既定値: 2）")
    quality_group.add_argument("--bitrate", type=str,
                               help="固定ビットレート。例: 192k, 320k")
    parser.add_argument("--overwrite", action="store_true", help="既存の出力ファイルを置き換える")
    parser.add_argument("--dry-run", action="store_true", help="変換予定だけを表示")
    parser.add_argument("--vgmstream", help="vgmstream-cli実行ファイルのパス")
    parser.add_argument("--ffmpeg", help="FFmpeg実行ファイルのパス")
    args = parser.parse_args(argv)
    if args.format != "mp3" and (args.quality is not None or args.bitrate):
        parser.error("--quality と --bitrate は --format mp3 でのみ使えます")
    if args.bitrate and not re.fullmatch(r"(?:32|40|48|56|64|80|96|112|128|160|192|224|256|320)k", args.bitrate.lower()):
        parser.error("--bitrate は 32k, 128k, 192k など有効なMP3ビットレートを指定してください")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source_arg = args.input.expanduser().resolve()
        sources = discover_sources(source_arg, args.recursive)
        input_root = source_arg if source_arg.is_dir() else source_arg.parent
        default_folder = "mp3" if args.format == "mp3" else args.format
        output_root = args.output.expanduser().resolve() if args.output else input_root / default_folder
        jobs = build_jobs(sources, input_root, output_root, args.format)
    except (SetupError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    summary = Summary()
    ready: list[Job] = []
    for job in jobs:
        if job.output.exists() and not args.overwrite:
            summary.skipped += 1
            print(f"[スキップ] {job.source} → {job.output}（出力済み）")
        else:
            ready.append(job)
    if args.dry_run:
        for job in ready:
            print(f"[予定] {job.source} → {job.output}")
        for job in jobs:
            if job not in ready:
                print(f"[スキップ] {job.source} → {job.output}（出力済み）")
        print(f"合計: {len(jobs)} 件（変換予定 {len(ready)}、スキップ {summary.skipped}）")
        return 0
    if not ready:
        print(f"合計: 成功 {summary.success}、スキップ {summary.skipped}、失敗 {summary.failed}")
        return 0

    try:
        from app_paths import get_settings

        settings = get_settings()
        vgmstream = resolve_tool(args.vgmstream, "vgmstream-cli", settings.get("vgmstream_path"))
        ffmpeg = resolve_tool(args.ffmpeg, "ffmpeg", settings.get("ffmpeg_path"))
        ensure_ffmpeg(ffmpeg)
        if args.format == "mp3":
            ensure_mp3_encoder(ffmpeg)
    except SetupError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    try:
        quality = args.quality if args.quality is not None else (None if args.bitrate else 2)
        batch = convert_batch(
            ready, vgmstream, ffmpeg, quality, args.bitrate, args.overwrite,
            progress=lambda stage, source, index, total: print(f"[{index}/{total}] {stage}: {source}"),
            output_format=args.format,
        )
        summary.success += batch.success
        summary.failed += batch.failed
        if batch.cancelled:
            print("\nユーザーが処理を中断しました。", file=sys.stderr)
            return 130
    except KeyboardInterrupt:
        print("\nユーザーが処理を中断しました。", file=sys.stderr)
        print(f"集計: 成功 {summary.success}、スキップ {summary.skipped}、失敗 {summary.failed}")
        return 130
    print(f"合計: 成功 {summary.success}、スキップ {summary.skipped}、失敗 {summary.failed}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
