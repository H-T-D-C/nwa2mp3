"""Pinned, hash-checked, per-user installation of the conversion tools."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from app_paths import get_settings, resource_path, save_settings, tools_dir
from nwa_conversion import SetupError, ensure_ffmpeg, resolve_tool, run_process


Catalog = dict[str, dict[str, object]]
InstallerProgress = Callable[[str, int | None], None]
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    "gyan.dev", "www.gyan.dev",
}
CHUNK_SIZE = 256 * 1024
NETWORK_TIMEOUT = 15


def load_catalog() -> Catalog:
    try:
        data = json.loads(resource_path("resources/tool_catalog.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"ツール情報を読み込めません: {exc}") from exc
    if data.get("schema_version") != 1 or data.get("platform") != "windows-x64":
        raise SetupError("このWindows環境用のツール情報がありません。")
    tools = data.get("tools")
    if not isinstance(tools, dict) or not {"vgmstream", "ffmpeg"} <= tools.keys():
        raise SetupError("ツール情報に必要な項目がありません。")
    return tools


def tool_directory(name: str, definition: dict[str, object]) -> Path:
    return tools_dir() / name / str(definition["version"])


def executable_path(name: str, definition: dict[str, object]) -> Path:
    return tool_directory(name, definition) / str(definition["executable"])


def _cancel(cancel_event: threading.Event) -> None:
    if cancel_event.is_set():
        raise InterruptedError("導入を中止しました")


def _validated_url(url: str) -> urllib.request.Request:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise SetupError("許可されていない配布元です。アプリを最新版にしてください。")
    return urllib.request.Request(url, headers={"User-Agent": "Nwa2Mp3-Setup/1.0"})


def _download(
    url: str, target: Path, max_bytes: int, cancel_event: threading.Event,
    progress: InstallerProgress,
) -> str:
    _cancel(cancel_event)
    request = _validated_url(url)
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response, target.open("wb") as out:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise SetupError("ダウンロード先が許可されたHTTPS配布元ではありません。")
        header_size = response.headers.get("Content-Length")
        expected_size = int(header_size) if header_size and header_size.isdigit() else None
        if expected_size and expected_size > max_bytes:
            raise SetupError("配布アーカイブが想定サイズを超えています。")
        progress("ダウンロード中", 0)
        last_percentage: int | None = 0
        last_reported = time.monotonic()
        while True:
            _cancel(cancel_event)
            try:
                block = response.read(CHUNK_SIZE)
            except (TimeoutError, socket.timeout) as exc:
                raise SetupError("ダウンロードがタイムアウトしました。再試行するか、手動導入をご利用ください。") from exc
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise SetupError("ダウンロードしたファイルが想定サイズを超えています。")
            digest.update(block)
            out.write(block)
            percentage = min(99, int(total * 100 / expected_size)) if expected_size else None
            now = time.monotonic()
            if percentage != last_percentage or (percentage is None and now - last_reported >= 0.25):
                progress("ダウンロード中", percentage)
                last_percentage = percentage
                last_reported = now
    if expected_size is not None and total != expected_size:
        raise SetupError("ダウンロードが途中で終了しました。もう一度お試しください。")
    return digest.hexdigest()


def safe_extract(zip_path: Path, destination: Path, max_unpacked_bytes: int) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    total_size = 0
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if len(members) > 20000:
                raise SetupError("ZIPのファイル数が想定を超えています。")
            for member in members:
                raw = member.filename.replace("\\", "/")
                posix = PurePosixPath(raw)
                windows = PureWindowsPath(raw)
                if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
                    raise SetupError("ZIP内に許可されないパスが含まれています。")
                mode = (member.external_attr >> 16) & 0xFFFF
                if mode and (mode & 0o170000) == 0o120000:
                    raise SetupError("ZIP内のシンボリックリンクには対応していません。")
                target = (root / Path(*posix.parts)).resolve()
                if not target.is_relative_to(root):
                    raise SetupError("ZIP内のパスが展開先の外を指しています。")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                total_size += member.file_size
                if total_size > max_unpacked_bytes:
                    raise SetupError("展開後のサイズが想定を超えています。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as out:
                    shutil.copyfileobj(source, out, CHUNK_SIZE)
                extracted.append(target)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise SetupError(f"ZIPを展開できません: {exc}") from exc
    return root


def _find_executable(root: Path, relative: str) -> Path:
    expected = Path(relative)
    direct = root / expected
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(expected.name), key=lambda path: str(path).casefold())
    for candidate in matches:
        if candidate.is_file() and candidate.relative_to(root).parts[-len(expected.parts):] == expected.parts:
            return candidate
    raise SetupError(f"配布ZIPに{expected.name}が見つかりません。")


def verify_tool(name: str, executable: Path) -> None:
    if name == "ffmpeg":
        ensure_ffmpeg(str(executable))
        return
    try:
        result = run_process([str(executable), "-V"])
    except OSError as exc:
        raise SetupError(f"NWA読み取りツールを実行できません: {exc}") from exc
    # vgmstream returns 1 for informational commands, including a valid -V.
    # Check its structured version/format response instead of assuming exit 0.
    try:
        info = json.loads(result.stdout)
        version = info.get("version")
        extensions = info.get("extensions", {}).get("vgm", [])
    except (json.JSONDecodeError, AttributeError):
        raise SetupError("NWA読み取りツールの動作を確認できませんでした。") from None
    if (
        result.returncode not in (0, 1) or not isinstance(version, str) or not version
        or not isinstance(extensions, list) or "nwa" not in extensions
    ):
        raise SetupError("NWA読み取りツールの動作を確認できませんでした。")


def check_tools(settings: dict[str, object] | None = None) -> dict[str, tuple[bool, str]]:
    settings = settings or {}
    catalog = load_catalog()
    status: dict[str, tuple[bool, str]] = {}
    for name, definition in catalog.items():
        try:
            command_name = "vgmstream-cli" if name == "vgmstream" else "ffmpeg"
            resolved = resolve_tool(settings.get(f"{name}_path"), command_name)
            executable = Path(resolved)
            verify_tool(name, executable)
            status[name] = (True, str(executable))
        except SetupError as exc:
            status[name] = (False, str(exc))
    return status


def install_tool(
    name: str, cancel_event: threading.Event | None = None,
    progress: InstallerProgress | None = None,
) -> Path:
    if os.name != "nt":
        raise SetupError("変換ツールの自動導入はWindows版で利用できます。")
    cancel_event = cancel_event or threading.Event()
    progress = progress or (lambda _message, _percent: None)
    catalog = load_catalog()
    if name not in catalog:
        raise SetupError("不明なツール名です。")
    definition = catalog[name]
    final_directory = tool_directory(name, definition)
    final_executable = executable_path(name, definition)
    if final_executable.is_file():
        try:
            verify_tool(name, final_executable)
            _remember_tool(name, final_executable)
            return final_executable
        except SetupError:
            pass

    staging_root = tools_dir() / name
    staging_root.mkdir(parents=True, exist_ok=True)
    download_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=".setup-", dir=staging_root) as temp:
            temp_dir = Path(temp)
            download_path = temp_dir / "download.zip"
            progress("ダウンロードを準備中", 0)
            digest = _download(
                str(definition["download_url"]), download_path,
                int(definition["max_download_bytes"]), cancel_event, progress,
            )
            if digest.casefold() != str(definition["sha256"]).casefold():
                raise SetupError("ファイルの安全性を確認できませんでした（SHA-256不一致）。")
            _cancel(cancel_event)
            installed = _publish_archive(name, definition, download_path, cancel_event, progress, temp_dir)
            _remember_tool(name, installed)
            return installed
    except InterruptedError as exc:
        raise SetupError(str(exc)) from exc
    except urllib.error.URLError as exc:
        raise SetupError(f"ダウンロードに接続できません。ネットワークを確認してください。\n{exc}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise SetupError("ダウンロードがタイムアウトしました。もう一度お試しください。") from exc
    finally:
        if download_path and download_path.exists():
            download_path.unlink(missing_ok=True)


def _remember_tool(name: str, executable: Path) -> None:
    settings = get_settings()
    settings[f"{name}_path"] = str(executable)
    save_settings(settings)


def _publish_archive(
    name: str, definition: dict[str, object], archive: Path,
    cancel_event: threading.Event, progress: InstallerProgress,
    temp_dir: Path,
) -> Path:
    final_directory = tool_directory(name, definition)
    staging_root = tools_dir() / name
    progress("ファイルを展開中", None)
    extracted_path = safe_extract(
        archive, temp_dir / "extracted", int(definition["max_unpacked_bytes"]),
    )
    executable = _find_executable(extracted_path, str(definition["executable"]))
    verify_tool(name, executable)
    relative_executable = executable.relative_to(extracted_path)
    source_root = extracted_path
    sibling_dirs = [
        child for child in extracted_path.iterdir()
        if child.is_dir() and executable.is_relative_to(child)
    ]
    if len(sibling_dirs) == 1 and len(list(extracted_path.iterdir())) == 1:
        source_root = sibling_dirs[0]
        relative_executable = executable.relative_to(source_root)
    publish_path = temp_dir / "publish"
    shutil.move(str(source_root), str(publish_path))
    _cancel(cancel_event)
    progress("導入を確認中", None)
    verify_tool(name, publish_path / relative_executable)
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    backup = final_directory.with_name(final_directory.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if final_directory.exists():
        os.replace(final_directory, backup)
    try:
        os.replace(publish_path, final_directory)
    except OSError:
        if backup.exists() and not final_directory.exists():
            os.replace(backup, final_directory)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    progress("導入完了", 100)
    return executable_path(name, definition)


def install_archive(
    archive: Path, cancel_event: threading.Event | None = None,
    progress: InstallerProgress | None = None,
) -> list[str]:
    """Install an offline ZIP only when it exactly matches a pinned archive."""
    cancel_event = cancel_event or threading.Event()
    progress = progress or (lambda _message, _percent: None)
    try:
        actual_size = archive.stat().st_size
    except OSError as exc:
        raise SetupError(f"ZIPを読み取れません: {exc}") from exc
    catalog = load_catalog()
    for name, definition in catalog.items():
        if actual_size > int(definition["max_download_bytes"]):
            continue
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            while block := stream.read(CHUNK_SIZE):
                _cancel(cancel_event)
                digest.update(block)
        if digest.hexdigest().casefold() != str(definition["sha256"]).casefold():
            continue
        tool_root = tools_dir() / name
        tool_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".setup-", dir=tool_root) as temp:
                result = _publish_archive(name, definition, archive, cancel_event, progress, Path(temp))
            _remember_tool(name, result)
            return [name]
        except InterruptedError as exc:
            raise SetupError(str(exc)) from exc
    raise SetupError("このZIPは対応版と一致しません。公式の指定バージョンを選んでください。")


def save_tool_path(name: str, executable: Path, settings: dict[str, object]) -> dict[str, object]:
    verify_tool(name, executable)
    updated = dict(settings)
    updated[f"{name}_path"] = str(executable.resolve())
    save_settings(updated)
    return updated
