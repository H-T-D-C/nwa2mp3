"""GUI event regressions without a display or external tools."""

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nwa_gui import NwaApp


class SetupEventTests(unittest.TestCase):
    def setUp(self):
        self.app = NwaApp.__new__(NwaApp)
        self.app.root = Mock()
        self.app.events = queue.Queue()
        self.app.cancel_event = threading.Event()
        self.app.setup_status = Mock()
        self.app.setup_progress = Mock()
        self.app.setup_busy = True
        self.app.pending_close = False
        self.app._set_setup_busy = Mock()
        self.app._update_setup_status = Mock()
        self.app._append_log = Mock()
        alerts = patch("nwa_gui.messagebox")
        self.alerts = alerts.start()
        self.addCleanup(alerts.stop)

    def test_download_progress_does_not_become_an_install_error(self):
        cancel_event = self.app.cancel_event
        self.app.events.put(("installer_progress", ("vgmstream", "ダウンロード中", 46)))

        self.app._drain_events()

        self.app.setup_status.configure.assert_called_once_with(text="音声読み取りツール: ダウンロード中 46%")
        self.app.setup_progress.configure.assert_called_once_with(mode="determinate", value=46)
        self.app._set_setup_busy.assert_not_called()
        self.app._update_setup_status.assert_not_called()
        self.assertIs(self.app.cancel_event, cancel_event)
        self.alerts.showerror.assert_not_called()
        self.app.root.after.assert_called_once()

    def test_progress_then_completion_releases_controls_once(self):
        for percentage in range(50):
            self.app.events.put(("installer_progress", ("ffmpeg", "ダウンロード中", percentage)))
        self.app.events.put(("install_done", None))

        self.app._drain_events()

        self.app._set_setup_busy.assert_called_once_with(False)
        self.app._update_setup_status.assert_called_once_with(hide_when_ready=True)
        self.assertIsNone(self.app.cancel_event)
        self.alerts.showerror.assert_not_called()

    def test_real_failure_is_shown_inline_once_and_can_be_retried(self):
        self.app.events.put(("installer_progress", ("vgmstream", "ダウンロード中", 46)))
        self.app.events.put(("install_error", RuntimeError("ネットワークに接続できません")))

        self.app._drain_events()
        self.app._drain_events()

        self.app._set_setup_busy.assert_called_once_with(False)
        self.app._update_setup_status.assert_called_once_with(hide_when_ready=False)
        text = self.app.setup_status.configure.call_args.kwargs["text"]
        self.assertIn("ネットワークに接続できません", text)
        self.assertIn("セットアップガイド", text)
        self.app._append_log.assert_called_once_with(text)
        self.alerts.showerror.assert_not_called()

    def test_offline_zip_failure_uses_the_same_inline_error(self):
        self.app.events.put(("zip_install_error", RuntimeError("未対応ZIP")))

        self.app._drain_events()

        self.app._set_setup_busy.assert_called_once_with(False)
        self.assertIn("未対応ZIP", self.app.setup_status.configure.call_args.kwargs["text"])
        self.alerts.showerror.assert_not_called()

    def test_cancelled_setup_does_not_display_a_failure(self):
        self.app.cancel_event.set()
        self.app.events.put(("installer_progress", ("vgmstream", "ダウンロード中", 46)))
        self.app.events.put(("install_error", RuntimeError("導入を中止しました")))

        self.app._drain_events()

        self.app.setup_progress.configure.assert_not_called()
        self.app._set_setup_busy.assert_called_once_with(False)
        self.assertIn("導入を中止しました", self.app.setup_status.configure.call_args.kwargs["text"])
        self.app._append_log.assert_not_called()
        self.alerts.showerror.assert_not_called()

    def test_large_progress_queue_yields_to_the_gui(self):
        for _ in range(120):
            self.app.events.put(("installer_progress", ("vgmstream", "ダウンロード中", 46)))

        self.app._drain_events()

        self.assertEqual(self.app.events.qsize(), 20)
        self.app.root.after.assert_called_once()
        self.alerts.showerror.assert_not_called()

    def test_preview_runs_in_a_worker_and_updates_the_selected_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "音声 サンプル.nwa"
            source.touch()
            signature = (str(source), "", False, False, "おすすめ（標準）", "", "mp3")
            self.app.preview_revision = 1
            self.app.preview_text = Mock()
            self.app._selection_signature = Mock(return_value=signature)
            with patch("nwa_gui.threading.Thread") as thread:
                self.app._start_preview(1, signature)
                thread.return_value.start.assert_called_once()
                thread.call_args.kwargs["target"]()

            self.app._drain_events()

            self.assertEqual(len(self.app.preview_jobs), 1)
            self.assertEqual(self.app.preview_jobs[0].source, source.resolve())
            self.assertIn("対象 1 曲", self.app.preview_text.set.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
