import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import nwa_conversion as app


class BatchTests(unittest.TestCase):
    def test_batch_reports_progress_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = []
            for name in ("01.nwa", "02.nwa", "03.nwa"):
                source = root / name
                source.touch()
                jobs.append(app.Job(source, root / (source.stem + ".mp3")))
            (root / "03.mp3").touch()
            phases = []

            def convert(job, *_args):
                if job.source.name == "01.nwa":
                    raise app.ConversionError("bad input")

            with patch.object(app, "convert_one", side_effect=convert):
                summary = app.convert_batch(
                    jobs, "vgm", "ffmpeg", 2, None, False,
                    progress=lambda stage, source, index, total: phases.append((stage, source.name, index, total)),
                )
            self.assertEqual((summary.success, summary.skipped, summary.failed), (1, 1, 1))
            self.assertEqual(phases[-1], ("スキップ", "03.nwa", 3, 3))

    def test_batch_cancellation_stops_before_next_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = []
            for name in ("01.nwa", "02.nwa"):
                source = root / name
                source.touch()
                jobs.append(app.Job(source, root / (source.stem + ".mp3")))
            event = threading.Event()
            attempted = []

            def cancel(*_args):
                attempted.append(True)
                event.set()
                raise app.ConversionCancelled("cancelled")

            with patch.object(app, "convert_one", side_effect=cancel):
                result = app.convert_batch(jobs, "vgm", "ffmpeg", 2, None, False, event)
            self.assertTrue(result.cancelled)
            self.assertEqual(len(attempted), 1)


if __name__ == "__main__":
    unittest.main()
