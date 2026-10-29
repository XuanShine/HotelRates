"""Google Sheets HTTP calls must time out and retry, not block forever."""
import sys
import threading
import time
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hotelrates.adapters.http_timeout import mount_http_timeouts
from fake_server import ScriptedServer


def finish_within(fn, seconds):
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError(f"call still blocked after {seconds}s")
    return box


class HttpTimeoutTests(unittest.TestCase):
    def _session(self, timeout, retries, backoff_factor=0):
        session = requests.Session()
        mount_http_timeouts(
            session,
            timeout=timeout,
            retries=retries,
            backoff_factor=backoff_factor,
        )
        return session

    def test_adapter_covers_sheet_writes_and_reads(self):
        session = self._session((10, 60), retries=2, backoff_factor=0.5)
        adapter = session.get_adapter("https://sheets.googleapis.com/v4/spreadsheets")
        retry = adapter.max_retries
        self.assertEqual(adapter.timeout, (10, 60))
        self.assertEqual(retry.total, 2)
        self.assertIn("POST", retry.allowed_methods)
        self.assertIn("PUT", retry.allowed_methods)
        self.assertIn("GET", retry.allowed_methods)
        self.assertIn(503, retry.status_forcelist)
        self.assertFalse(retry.respect_retry_after_header)

    def test_stalled_server_times_out_and_retries(self):
        with ScriptedServer([None, None]) as server:
            session = self._session((0.3, 0.4), retries=1)
            started = time.monotonic()
            box = finish_within(
                lambda: session.get(server.url, timeout=None),
                5,
            )
            elapsed = time.monotonic() - started
        exc = box.get("exc")
        self.assertIsInstance(exc, requests.RequestException)
        self.assertIn("timed out", str(exc).lower())
        self.assertEqual(server.requests, 2)
        self.assertGreaterEqual(elapsed, 0.6)
        self.assertLess(elapsed, 5)

    def test_success_is_unchanged(self):
        body = b"ok"
        with ScriptedServer([body]) as server:
            session = self._session((1, 2), retries=2)
            box = finish_within(lambda: session.get(server.url, timeout=None), 3)
        self.assertNotIn("exc", box, box.get("exc"))
        self.assertEqual(box["value"].status_code, 200)
        self.assertEqual(box["value"].content, body)
        self.assertEqual(server.requests, 1)

    def test_503_is_retried_then_succeeds(self):
        with ScriptedServer(
            [
                (503, "Service Unavailable", b"busy"),
                (200, "OK", b"done"),
            ]
        ) as server:
            session = self._session((1, 2), retries=2)
            box = finish_within(lambda: session.get(server.url, timeout=None), 3)
        self.assertNotIn("exc", box, box.get("exc"))
        self.assertEqual(box["value"].status_code, 200)
        self.assertEqual(box["value"].content, b"done")
        self.assertEqual(server.requests, 2)


if __name__ == "__main__":
    unittest.main()
