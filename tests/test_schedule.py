from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import run


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(core, "ROOT", self.root)
        self.root_patch.start()
        self.config = {"timezone": "America/New_York", "prepare_at": "07:00", "send_at": "08:30"}

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def mode(self, timestamp):
        return run.scheduled_mode(self.config, datetime.fromisoformat(timestamp))

    def test_morning_cutoff_prevents_early_work(self):
        self.assertIsNone(self.mode("2026-10-20T10:59:00+00:00"))
        self.assertEqual(self.mode("2026-10-20T11:00:00+00:00"), "prepare")

    def test_ready_issue_waits_until_publication_deadline(self):
        folder = self.root / "archive/20261020"
        core.write_json(folder / "prepared.json", {"date": "2026-10-20"})
        self.assertIsNone(self.mode("2026-10-20T12:29:59+00:00"))
        self.assertEqual(self.mode("2026-10-20T12:30:00+00:00"), "full")

    def test_late_trigger_recovers_missed_preparation(self):
        for timestamp in ("2026-10-20T12:45:00+00:00", "2026-10-20T13:10:00+00:00"):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(self.mode(timestamp), "full")

    def test_completed_issue_skips_every_retry(self):
        core.write_json(self.root / "archive/20261020/receipt.json", {"status": "published"})
        for timestamp in ("2026-10-20T11:17:00+00:00", "2026-10-20T12:30:00+00:00",
                          "2026-10-20T12:45:00+00:00", "2026-10-20T13:10:00+00:00"):
            with self.subTest(timestamp=timestamp):
                self.assertIsNone(self.mode(timestamp))

    def test_deadline_tracks_dst_and_standard_time(self):
        for timestamp in ("2026-03-08T12:30:00+00:00", "2026-10-20T12:30:00+00:00",
                          "2026-11-01T13:30:00+00:00", "2026-12-15T13:30:00+00:00"):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(self.mode(timestamp), "full")

    def test_receipt_uses_local_date_instead_of_utc_date(self):
        core.write_json(self.root / "archive/20261019/receipt.json", {"status": "published"})
        self.assertIsNone(self.mode("2026-10-20T00:10:00+00:00"))
        self.assertEqual(self.mode("2026-10-20T12:30:00+00:00"), "full")

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.mode("2026-10-20T08:30:00")

    def test_invalid_deadline_order_is_rejected(self):
        self.config["prepare_at"] = "09:00"
        with self.assertRaisesRegex(ValueError, "earlier"):
            self.mode("2026-10-20T12:30:00+00:00")
