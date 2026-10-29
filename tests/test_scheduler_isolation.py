"""A failed scheduler cycle must not block the jobs that are also due."""
import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hotelrates
import hotelrates.adapters

# scheduler imports these at module level; they pull in Sheets credentials.
for _name in (
    "hotelrates.veille_competitive",
    "hotelrates.internetPrice",
    "hotelrates.dispo",
    "hotelrates.price",
    "hotelrates.config",
    "hotelrates.adapters.sheets",
):
    sys.modules.setdefault(_name, MagicMock())

from hotelrates import scheduler
import schedule


class SchedulerIsolationTests(unittest.TestCase):
    def setUp(self):
        schedule.clear()

    def tearDown(self):
        schedule.clear()

    def test_failed_job_does_not_block_the_next_job_or_the_next_cycle(self):
        calls = []

        def boom():
            calls.append("boom")
            raise RuntimeError("cycle failed")

        def ok():
            calls.append("ok")

        failed = schedule.every(10).minutes.do(boom)
        healthy = schedule.every(10).minutes.do(ok)
        past = datetime.datetime.now() - datetime.timedelta(seconds=1)
        failed.next_run = past
        healthy.next_run = past

        scheduler.run_due_jobs()

        self.assertEqual(calls, ["boom", "ok"])
        self.assertFalse(failed.should_run)
        self.assertFalse(healthy.should_run)
        self.assertGreater(failed.next_run, datetime.datetime.now())

        calls.clear()
        scheduler.run_due_jobs()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()