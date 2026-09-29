import hashlib
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import tool_setup
from nwa_conversion import SetupError


class Response:
    def __init__(self, payload: bytes, url: str):
        self.payload = payload
        self.url = url
        self.headers = {"Content-Length": str(len(payload))}
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, amount: int) -> bytes:
        result = self.payload[self.offset : self.offset + amount]
        self.offset += len(result)
        return result


def make_zip(entries: dict[str, bytes]) -> bytes:
    import io

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return stream.getvalue()


class DownloadTests(unittest.TestCase):
    def test_read_timeout_stops_the_download_instead_of_retrying_forever(self):
        response = Response(b"x", "https://github.com/archive.zip")
        response.read = Mock(side_effect=TimeoutError("no data"))
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tool_setup.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(SetupError, "タイムアウト"):
                    tool_setup._download(
                        "https://github.com/archive.zip", Path(temporary) / "package.zip", 1024,
                        threading.Event(), lambda *_args: None,
                    )
        response.read.assert_called_once()

    def test_download_enforces_https_host_and_sha256(self):
        payload = b"test package"
        response = Response(payload, "https://github.com/download/archive.zip")
        progress = []
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "package.zip"
            with patch.object(tool_setup.urllib.request, "urlopen", return_value=response):
                digest = tool_setup._download(
                    "https://github.com/example/archive.zip", target, 1024,
                    threading.Event(), lambda stage, percent: progress.append((stage, percent)),
                )
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(target.read_bytes(), payload)
            self.assertTrue(progress)

    def test_download_rejects_http_and_unapproved_hosts(self):
        for url in ("http://github.com/file.zip", "https://example.com/file.zip"):
            with self.subTest(url=url), self.assertRaises(SetupError):
                tool_setup._validated_url(url)

    def test_download_rejects_redirect_to_unapproved_host(self):
        response = Response(b"x", "https://example.com/archive.zip")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tool_setup.urllib.request, "urlopen", return_value=response):
                with self.assertRaises(SetupError):
                    tool_setup._download(
                        "https://github.com/archive.zip", Path(temporary) / "bad.zip", 1024,
                        threading.Event(), lambda *_args: None,
                    )

    def test_download_cancellation_does_not_start_request(self):
        event = threading.Event()
        event.set()
        response = Response(b"x", "https://github.com/archive.zip")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "package.zip"
            with patch.object(tool_setup.urllib.request, "urlopen", return_value=response):
                with self.assertRaises(InterruptedError):
                    tool_setup._download(
                        "https://github.com/archive.zip", target, 1024, event,
                        lambda *_args: None,
                    )


class ToolVerificationTests(unittest.TestCase):
    def test_vgmstream_version_json_with_exit_one_is_accepted(self):
        result = subprocess.CompletedProcess([], 1, '{"version":"r2117","extensions":{"vgm":["nwa"]}}', "")
        with patch.object(tool_setup, "run_process", return_value=result) as run:
            tool_setup.verify_tool("vgmstream", Path("vgmstream-cli.exe"))
        run.assert_called_once_with(["vgmstream-cli.exe", "-V"])

    def test_vgmstream_failure_or_missing_nwa_support_is_rejected(self):
        for result in (
            subprocess.CompletedProcess([], 1, "vgmstream failed to load", "missing DLL"),
            subprocess.CompletedProcess([], 1, '{"version":"r2117","extensions":{"vgm":["ogg"]}}', ""),
            subprocess.CompletedProcess([], 3, '{"version":"r2117","extensions":{"vgm":["nwa"]}}', ""),
        ):
            with self.subTest(result=result), patch.object(tool_setup, "run_process", return_value=result):
                with self.assertRaises(SetupError):
                    tool_setup.verify_tool("vgmstream", Path("vgmstream-cli.exe"))


class ArchiveTests(unittest.TestCase):
    def test_safe_extract_extracts_nested_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "good.zip"
            archive.write_bytes(make_zip({"bundle/bin/ffmpeg.exe": b"exe", "bundle/LICENSE.txt": b"license"}))
            destination = tool_setup.safe_extract(archive, root / "out", 1000)
            self.assertEqual((destination / "bundle" / "bin" / "ffmpeg.exe").read_bytes(), b"exe")

    def test_safe_extract_rejects_zip_slip_without_writing_outside(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.zip"
            archive.write_bytes(make_zip({"../outside.txt": b"bad"}))
            with self.assertRaises(SetupError):
                tool_setup.safe_extract(archive, root / "out", 1000)
            self.assertFalse((root / "outside.txt").exists())

    def test_safe_extract_rejects_expansion_size_over_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "large.zip"
            archive.write_bytes(make_zip({"large.bin": b"12345"}))
            with self.assertRaises(SetupError):
                tool_setup.safe_extract(archive, root / "out", 4)

    def test_safe_extract_rejects_absolute_windows_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.zip"
            archive.write_bytes(make_zip({"C:/outside.txt": b"bad"}))
            with self.assertRaises(SetupError):
                tool_setup.safe_extract(archive, root / "out", 1000)

    def test_offline_zip_requires_exact_catalog_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "unsupported.zip"
            archive.write_bytes(make_zip({"unknown.exe": b"not a supported package"}))
            with patch.object(tool_setup, "tools_dir", return_value=Path(temporary) / "tools"):
                with self.assertRaises(SetupError):
                    tool_setup.install_archive(archive)

    def test_offline_zip_catalog_values_are_pinned(self):
        catalog = tool_setup.load_catalog()
        for name, definition in catalog.items():
            with self.subTest(name=name):
                self.assertRegex(str(definition["sha256"]), r"^[0-9a-f]{64}$")
                self.assertTrue(str(definition["download_url"]).startswith("https://"))
                self.assertLess(int(definition["max_download_bytes"]), 200_000_000)

    def test_offline_install_verifies_and_publishes_pinned_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = make_zip({"bundle/bin/ffmpeg.exe": b"test executable"})
            archive = root / "ffmpeg.zip"
            archive.write_bytes(payload)
            definition = {
                "version": "test1", "executable": "bin/ffmpeg.exe",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "max_download_bytes": 10000, "max_unpacked_bytes": 10000,
            }
            tools = root / "user-tools"
            with patch.object(tool_setup, "load_catalog", return_value={"ffmpeg": definition}):
                with patch.object(tool_setup, "tools_dir", return_value=tools):
                    with patch.object(tool_setup, "verify_tool"):
                        with patch.object(tool_setup, "get_settings", return_value={}):
                            with patch.object(tool_setup, "save_settings") as save:
                                installed = tool_setup.install_archive(archive)
            self.assertEqual(installed, ["ffmpeg"])
            final_exe = tools / "ffmpeg" / "test1" / "bin" / "ffmpeg.exe"
            self.assertEqual(final_exe.read_bytes(), b"test executable")
            save.assert_called_once()

    def test_bad_replacement_archive_preserves_existing_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            known = make_zip({"bundle/bin/ffmpeg.exe": b"expected tool"})
            archive = root / "wrong.zip"
            archive.write_bytes(make_zip({"bundle/bin/ffmpeg.exe": b"bad replacement"}))
            definition = {
                "version": "test1", "executable": "bin/ffmpeg.exe",
                "sha256": hashlib.sha256(known).hexdigest(),
                "max_download_bytes": 10000, "max_unpacked_bytes": 10000,
            }
            tools = root / "user-tools"
            old_exe = tools / "ffmpeg" / "test1" / "bin" / "ffmpeg.exe"
            old_exe.parent.mkdir(parents=True)
            old_exe.write_bytes(b"old working tool")
            with patch.object(tool_setup, "load_catalog", return_value={"ffmpeg": definition}):
                with patch.object(tool_setup, "tools_dir", return_value=tools):
                    with self.assertRaises(SetupError):
                        tool_setup.install_archive(archive)
            self.assertEqual(old_exe.read_bytes(), b"old working tool")


class AutomaticInstallTests(unittest.TestCase):
    def test_automatic_install_saves_nested_ffmpeg_executable_for_next_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = make_zip({"bundle/bin/ffmpeg.exe": b"test executable"})
            definition = {
                "version": "test1", "executable": "bin/ffmpeg.exe",
                "download_url": "https://github.com/archive.zip",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "max_download_bytes": 10000, "max_unpacked_bytes": 10000,
            }
            with (
                patch.object(tool_setup, "os", wraps=os) as platform,
                patch.object(tool_setup, "load_catalog", return_value={"ffmpeg": definition}),
                patch.object(tool_setup, "tools_dir", return_value=root / "tools"),
                patch.object(tool_setup, "verify_tool"),
                patch.object(tool_setup, "get_settings", return_value={"last_input": "keep.nwa"}),
                patch.object(tool_setup, "save_settings") as save,
                patch.object(tool_setup.urllib.request, "urlopen", return_value=Response(payload, definition["download_url"])),
            ):
                platform.name = "nt"
                installed = tool_setup.install_tool("ffmpeg")
            self.assertEqual(installed.read_bytes(), b"test executable")
            save.assert_called_once_with({"last_input": "keep.nwa", "ffmpeg_path": str(installed)})

    def test_existing_install_is_remembered_without_downloading_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "ffmpeg" / "test1" / "bin" / "ffmpeg.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            definition = {"version": "test1", "executable": "bin/ffmpeg.exe"}
            with (
                patch.object(tool_setup, "os", wraps=os) as platform,
                patch.object(tool_setup, "load_catalog", return_value={"ffmpeg": definition}),
                patch.object(tool_setup, "tools_dir", return_value=root),
                patch.object(tool_setup, "verify_tool"),
                patch.object(tool_setup, "get_settings", return_value={}),
                patch.object(tool_setup, "save_settings") as save,
                patch.object(tool_setup, "_download") as download,
            ):
                platform.name = "nt"
                self.assertEqual(tool_setup.install_tool("ffmpeg"), executable)
            download.assert_not_called()
            save.assert_called_once_with({"ffmpeg_path": str(executable)})


if __name__ == "__main__":
    unittest.main()
