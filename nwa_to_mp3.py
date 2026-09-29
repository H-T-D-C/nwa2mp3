#!/usr/bin/env python3
"""Batch-convert VisualArt's NWA audio to MP3."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
MP3_SAMPLE_RATES = {
    8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000,
}


class SetupError(Exception):
    """An error that prevents a conversion run from starting."""


class ConversionError(Exception):
    """A recoverable error converting one input file."""


@dataclass(frozen=True)
class Job:
    source: Path
    output: Path


@dataclass
class Summary:
    success: int = 0
    skipped: int = 0
    failed: int = 0


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


def build_jobs(sources: Sequence[Path], input_root: Path, output_root: Path) -> list[Job]:
    jobs: list[Job] = []
    seen: dict[str, Path] = {}
    for source in sources:
        relative = source.relative_to(input_root) if input_root.is_dir() else Path(source.name)
        output = (output_root / relative).with_suffix(".mp3").resolve()
        key = os.path.normcase(str(output))
        if key in seen:
            raise SetupError(f"出力名が衝突します: {seen[key]} と {source} → {output}")
        seen[key] = source
        jobs.append(Job(source, output))
    return jobs


def resolve_tool(explicit: str | None, name: str) -> str:
    """Resolve an explicitly configured, bundled, or PATH executable."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise SetupError(f"指定されたツールが見つかりません: {candidate}")
        return str(candidate.resolve())
    suffixes = (".exe", "") if os.name == "nt" else ("",)
    for suffix in suffixes:
        bundled = SCRIPT_DIR / "tools" / f"{name}{suffix}"
        if bundled.is_file():
            return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise SetupError(f"{name} が見つかりません。README.md の導入手順を確認してください。")


def run_process(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run without a shell, and stop the child promptly when interrupted."""
    process = subprocess.Popen(
        list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        stdout, stderr = process.communicate()
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


def decode_and_validate(vgmstream: str, source: Path, wav_path: Path) -> None:
    try:
        result = run_process([vgmstream, "-i", "-o", str(wav_path), str(source)])
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
) -> None:
    job.output.parent.mkdir(parents=True, exist_ok=True)
    temp_mp3: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="nwa2mp3-") as temp_dir:
            wav_path = Path(temp_dir) / "decoded.wav"
            decode_and_validate(vgmstream, job.source, wav_path)
            with tempfile.NamedTemporaryFile(
                prefix=f".{job.output.stem}.", suffix=".tmp.mp3",
                dir=job.output.parent, delete=False,
            ) as temp_file:
                temp_mp3 = Path(temp_file.name)
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-i", str(wav_path), "-map", "0:a:0", "-vn"]
            command += ["-q:a", str(quality)] if quality is not None else ["-b:a", bitrate or "192k"]
            command += ["-f", "mp3", str(temp_mp3)]
            try:
                result = run_process(command)
            except OSError as exc:
                raise ConversionError(f"FFmpegを実行できません: {exc}") from exc
            if result.returncode:
                detail = (result.stderr or result.stdout or "詳細情報なし").strip()
                raise ConversionError(f"MP3のエンコードに失敗しました: {detail}")
            if not temp_mp3.is_file() or temp_mp3.stat().st_size == 0:
                raise ConversionError("FFmpegが有効なMP3を作成しませんでした。")
            if overwrite:
                os.replace(temp_mp3, job.output)
            else:
                # A hard link creates the final name atomically and never clobbers a race.
                os.link(temp_mp3, job.output)
                temp_mp3.unlink()
            temp_mp3 = None
    except OSError as exc:
        raise ConversionError(f"ファイルを作成・置換できません: {exc}") from exc
    finally:
        if temp_mp3 is not None:
            try:
                temp_mp3.unlink(missing_ok=True)
            except OSError:
                pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VisualArt's / RealLive形式のNWA音声をMP3へ一括変換します。"
    )
    parser.add_argument("input", type=Path, help="NWAファイルまたは入力フォルダー")
    parser.add_argument("--output", type=Path, help="出力フォルダー（既定値: 入力の mp3/）")
    parser.add_argument("--recursive", action="store_true", help="サブフォルダーも検索")
    quality_group = parser.add_mutually_exclusive_group()
    quality_group.add_argument("--quality", type=int, choices=range(10),
                               help="VBR品質 0～9（既定値: 2）")
    quality_group.add_argument("--bitrate", type=str,
                               help="固定ビットレート。例: 192k, 320k")
    parser.add_argument("--overwrite", action="store_true", help="既存MP3を置き換える")
    parser.add_argument("--dry-run", action="store_true", help="変換予定だけを表示")
    parser.add_argument("--vgmstream", help="vgmstream-cli実行ファイルのパス")
    parser.add_argument("--ffmpeg", help="FFmpeg実行ファイルのパス")
    args = parser.parse_args(argv)
    if args.bitrate and not re.fullmatch(r"(?:32|40|48|56|64|80|96|112|128|160|192|224|256|320)k", args.bitrate.lower()):
        parser.error("--bitrate は 32k, 128k, 192k など有効なMP3ビットレートを指定してください")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source_arg = args.input.expanduser().resolve()
        sources = discover_sources(source_arg, args.recursive)
        input_root = source_arg if source_arg.is_dir() else source_arg.parent
        output_root = args.output.expanduser().resolve() if args.output else input_root / "mp3"
        jobs = build_jobs(sources, input_root, output_root)
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
        vgmstream = resolve_tool(args.vgmstream, "vgmstream-cli")
        ffmpeg = resolve_tool(args.ffmpeg, "ffmpeg")
        ensure_mp3_encoder(ffmpeg)
    except SetupError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    try:
        for index, job in enumerate(ready, 1):
            print(f"[{index}/{len(ready)}] 変換中: {job.source}")
            try:
                quality = args.quality if args.quality is not None else (None if args.bitrate else 2)
                convert_one(job, vgmstream, ffmpeg, quality, args.bitrate, args.overwrite)
                summary.success += 1
                print(f"[成功] {job.output}")
            except ConversionError as exc:
                summary.failed += 1
                print(f"[失敗] {job.source}: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nユーザーが処理を中断しました。", file=sys.stderr)
        print(f"集計: 成功 {summary.success}、スキップ {summary.skipped}、失敗 {summary.failed}")
        return 130
    print(f"合計: 成功 {summary.success}、スキップ {summary.skipped}、失敗 {summary.failed}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
