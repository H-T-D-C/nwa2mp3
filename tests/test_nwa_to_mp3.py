import contextlib
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import nwa_conversion as app


def write_wav(path: Path, frames: int = 100, channels: int = 2, rate: int = 44100) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\0" * frames * channels * 2)


class ToolResolutionTests(unittest.TestCase):
    def test_managed_ffmpeg_bin_is_found_without_path_or_saved_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "ffmpeg" / "test1" / "bin" / "ffmpeg.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("app_paths.tools_dir", return_value=root):
                with patch.object(app.shutil, "which", return_value=None):
                    self.assertEqual(app.resolve_tool(None, "ffmpeg"), str(executable.resolve()))


class DiscoveryTests(unittest.TestCase):
    def test_single_file_accepts_case_insensitive_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "track.NWA"
            source.touch()
            self.assertEqual(app.discover_sources(source, False), [source.resolve()])

    def test_non_recursive_and_recursive_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "top.nwa").touch()
            (root / "sub").mkdir()
            (root / "sub" / "nested.NWA").touch()
            self.assertEqual(len(app.discover_sources(root, False)), 1)
            self.assertEqual(len(app.discover_sources(root, True)), 2)

    def test_discovery_is_sorted_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("z.nwa", "A.nwa"):
                (root / name).touch()
            self.assertEqual([p.name for p in app.discover_sources(root, False)], ["A.nwa", "z.nwa"])

    def test_empty_directory_and_missing_input_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(app.SetupError):
                app.discover_sources(Path(temporary), False)
            with self.assertRaises(app.SetupError):
                app.discover_sources(Path(temporary) / "missing.nwa", False)

    def test_output_mapping_preserves_relative_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "input" / "album" / "song.nwa"
            nested.parent.mkdir(parents=True)
            nested.touch()
            jobs = app.build_jobs([nested.resolve()], (root / "input").resolve(), root / "output")
            self.assertEqual(jobs[0].output, (root / "output" / "album" / "song.mp3").resolve())

    def test_duplicate_output_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "song.nwa"
            second = root / "song.NWA"
            first.touch()
            second.touch()
            with self.assertRaises(app.SetupError):
                app.build_jobs([first.resolve(), second.resolve()], root, root / "out")


class ConversionTests(unittest.TestCase):
    def test_validates_complete_pcm_wav(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, decoded = root / "source.nwa", root / "decoded.wav"
            source.touch()

            def fake_process(command, *_args):
                write_wav(decoded)
                return app.subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(app, "run_process", side_effect=fake_process):
                app.decode_and_validate("vgmstream-cli", source, decoded)

    def test_rejects_truncated_wav(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, decoded = root / "source.nwa", root / "decoded.wav"
            source.touch()

            def fake_process(command, *_args):
                write_wav(decoded)
                decoded.write_bytes(decoded.read_bytes()[:-20])
                return app.subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(app, "run_process", side_effect=fake_process):
                with self.assertRaises(app.ConversionError):
                    app.decode_and_validate("vgmstream-cli", source, decoded)

    def test_successful_conversion_uses_vbr_and_finalizes_mp3(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "input.nwa", root / "out" / "input.mp3"
            source.touch()

            def fake_process(command, *_args):
                if command[0] == "vgm":
                    write_wav(Path(command[command.index("-o") + 1]))
                else:
                    self.assertIn("-q:a", command)
                    Path(command[-1]).write_bytes(b"ID3fake")
                return app.subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(app, "run_process", side_effect=fake_process):
                app.convert_one(app.Job(source, output), "vgm", "ffmpeg", 2, None, False)
            self.assertEqual(output.read_bytes(), b"ID3fake")
            self.assertEqual(list(output.parent.glob("*.tmp.mp3")), [])

    def test_fixed_bitrate_is_forwarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "input.nwa", root / "out" / "input.mp3"
            source.touch()

            def fake_process(command, *_args):
                if command[0] == "vgm":
                    write_wav(Path(command[command.index("-o") + 1]))
                else:
                    self.assertEqual(command[command.index("-b:a") + 1], "192k")
                    Path(command[-1]).write_bytes(b"mp3")
                return app.subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(app, "run_process", side_effect=fake_process):
                app.convert_one(app.Job(source, output), "vgm", "ffmpeg", None, "192k", False)

    def test_failed_overwrite_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "input.nwa", root / "out" / "input.mp3"
            source.touch()
            output.parent.mkdir()
            output.write_bytes(b"original")

            def fake_process(command, *_args):
                if command[0] == "vgm":
                    write_wav(Path(command[command.index("-o") + 1]))
                    return app.subprocess.CompletedProcess(command, 0, "", "")
                return app.subprocess.CompletedProcess(command, 1, "", "encoder error")

            with patch.object(app, "run_process", side_effect=fake_process):
                with self.assertRaises(app.ConversionError):
                    app.convert_one(app.Job(source, output), "vgm", "ffmpeg", 2, None, True)
            self.assertEqual(output.read_bytes(), b"original")
            self.assertEqual(list(output.parent.glob("*.tmp.mp3")), [])

    def test_failed_decode_does_not_create_final_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "input.nwa", root / "out" / "input.mp3"
            source.touch()
            with patch.object(app, "run_process", return_value=app.subprocess.CompletedProcess([], 1, "", "bad NWA")):
                with self.assertRaises(app.ConversionError):
                    app.convert_one(app.Job(source, output), "vgm", "ffmpeg", 2, None, False)
            self.assertFalse(output.exists())


class CliTests(unittest.TestCase):
    def test_quality_and_bitrate_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            app.parse_args(["input.nwa", "--quality", "3", "--bitrate", "192k"])

    def test_bitrate_validation(self):
        with self.assertRaises(SystemExit):
            app.parse_args(["input.nwa", "--bitrate", "123k"])

    def test_dry_run_does_not_resolve_or_run_external_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "track.nwa").touch()
            output = io.StringIO()
            with patch.object(app, "resolve_tool", side_effect=AssertionError("dry run invoked a tool")):
                with contextlib.redirect_stdout(output):
                    result = app.main([str(root), "--output", str(root / "out"), "--dry-run"])
            self.assertEqual(result, 0)
            self.assertIn("[予定]", output.getvalue())
            self.assertFalse((root / "out").exists())

    def test_existing_outputs_are_skipped_without_tool_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "track.nwa").touch()
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "track.mp3").write_bytes(b"keep")
            with patch.object(app, "resolve_tool", side_effect=AssertionError("skip should not need tools")):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = app.main([str(root), "--output", str(output_dir)])
            self.assertEqual(result, 0)
            self.assertEqual((output_dir / "track.mp3").read_bytes(), b"keep")

    def test_preflight_input_error_returns_code_two_without_traceback(self):
        error_output = io.StringIO()
        with contextlib.redirect_stderr(error_output):
            result = app.main(["definitely-missing.nwa"])
        self.assertEqual(result, 2)
        self.assertIn("入力が見つかりません", error_output.getvalue())
        self.assertNotIn("Traceback", error_output.getvalue())

    def test_batch_continues_after_one_conversion_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("01.nwa", "02.nwa"):
                (root / name).touch()
            attempted = []

            def convert(job, *_args):
                attempted.append(job.source.name)
                if job.source.name == "01.nwa":
                    raise app.ConversionError("broken input")

            with patch.object(app, "resolve_tool", side_effect=["vgm", "ffmpeg"]):
                with patch.object(app, "ensure_mp3_encoder"):
                    with patch.object(app, "convert_one", side_effect=convert):
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            result = app.main([str(root), "--output", str(root / "out")])
            self.assertEqual(result, 1)
            self.assertEqual(attempted, ["01.nwa", "02.nwa"])


if __name__ == "__main__":
    unittest.main()
