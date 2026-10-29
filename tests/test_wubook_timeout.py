"""WuBook XML-RPC must time out and retry instead of blocking the scheduler."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.parsers.expat import ExpatError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import xmlrpc.client

from hotelrates import wubook_api
from fake_server import ScriptedServer

OK = b"""<?xml version='1.0'?>
<methodResponse>
  <params><param><value><array><data>
    <value><int>0</int></value>
    <value><string>tok</string></value>
  </data></array></value></param></params>
</methodResponse>
"""

UPDATED = b"""<?xml version='1.0'?>
<methodResponse>
  <params><param><value><array><data>
    <value><int>0</int></value>
    <value><string>Ok</string></value>
  </data></array></value></param></params>
</methodResponse>
"""

TRUNCATED = b"<?xml version='1.0'?><methodResponse><params>"

FAULT = b"""<?xml version='1.0'?>
<methodResponse>
  <fault><value><struct>
    <member><name>faultCode</name><value><int>1</int></value></member>
    <member><name>faultString</name><value><string>nope</string></value></member>
  </struct></value></fault>
</methodResponse>
"""


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


def wubook_env(url, **extra):
    values = dict(
        url=url,
        user="user",
        password="secret",
        pkey="pkey",
        lcode="1",
        RPC_BACKOFF_SECONDS=0,
        RPC_BACKOFF_MAX=0,
    )
    values.update(extra)
    return patch.multiple(wubook_api, **values)


class WubookTimeoutTests(unittest.TestCase):
    def test_stalled_server_times_out(self):
        with ScriptedServer([None]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=0.5, RPC_ATTEMPTS=1):
                started = time.monotonic()
                box = finish_within(wubook_api.Wubook, 3)
                elapsed = time.monotonic() - started
        self.assertIn("exc", box)
        self.assertIsInstance(box["exc"], TimeoutError)
        self.assertGreaterEqual(elapsed, 0.4)
        self.assertLess(elapsed, 3)
        self.assertEqual(server.requests, 1)

    def test_stalled_server_retries_then_fails(self):
        with ScriptedServer([None, None, None]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=0.4, RPC_ATTEMPTS=2):
                started = time.monotonic()
                box = finish_within(wubook_api.Wubook, 4)
                elapsed = time.monotonic() - started
        self.assertIsInstance(box.get("exc"), TimeoutError)
        self.assertEqual(server.requests, 2)
        self.assertGreaterEqual(elapsed, 0.7)
        self.assertLess(elapsed, 4)

    def test_truncated_xml_is_retried_then_connects(self):
        with ScriptedServer([TRUNCATED, TRUNCATED, OK, OK]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=3):
                box = finish_within(wubook_api.Wubook, 4)
        self.assertNotIn("exc", box)
        session = box["value"]
        self.assertEqual(session.returnCode, 0)
        self.assertEqual(session.token, "tok")
        # Two truncated replies, then a valid acquire. No release: the session
        # is not used as a context manager.
        self.assertEqual(server.requests, 3)

    def test_fault_is_not_retried(self):
        with ScriptedServer([FAULT, OK]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=3):
                box = finish_within(wubook_api.Wubook, 3)
        self.assertIsInstance(box.get("exc"), xmlrpc.client.Fault)
        self.assertEqual(server.requests, 1)

    def test_http_404_is_not_retried(self):
        with ScriptedServer([(404, "Not Found", b"missing"), OK]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=3):
                box = finish_within(wubook_api.Wubook, 3)
        self.assertIsInstance(box.get("exc"), xmlrpc.client.ProtocolError)
        self.assertEqual(box["exc"].errcode, 404)
        self.assertEqual(server.requests, 1)

    def test_http_503_is_retried(self):
        with ScriptedServer([(503, "Service Unavailable", b"busy"), OK, OK]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=3):
                box = finish_within(wubook_api.Wubook, 3)
        self.assertNotIn("exc", box)
        self.assertEqual(box["value"].token, "tok")
        self.assertEqual(server.requests, 2)

    def test_upload_retries_truncated_xml_then_releases(self):
        with ScriptedServer([OK, TRUNCATED, UPDATED, OK]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=3):
                box = finish_within(
                    lambda: wubook_api.upload_prices("29/10/2026", {"1": [80]}),
                    4,
                )
        self.assertNotIn("exc", box, getattr(box.get("exc"), "args", box))
        # acquire, failed update, retried update, release
        self.assertEqual(server.requests, 4)

    def test_release_stall_does_not_hang_or_raise(self):
        with ScriptedServer([OK, UPDATED, None]) as server:
            with wubook_env(server.url, RPC_TIMEOUT=0.5, RPC_ATTEMPTS=1):
                started = time.monotonic()
                box = finish_within(
                    lambda: wubook_api.upload_prices("29/10/2026", {"1": [80]}),
                    3,
                )
                elapsed = time.monotonic() - started
        self.assertNotIn("exc", box, box.get("exc"))
        self.assertGreaterEqual(elapsed, 0.4)
        self.assertEqual(server.requests, 3)

    def test_next_cycle_works_after_timeout(self):
        with ScriptedServer([None]) as stalled:
            with wubook_env(stalled.url, RPC_TIMEOUT=0.4, RPC_ATTEMPTS=1):
                box = finish_within(wubook_api.Wubook, 3)
        self.assertIsInstance(box.get("exc"), TimeoutError)

        with ScriptedServer([OK, OK]) as healthy:
            with wubook_env(healthy.url, RPC_TIMEOUT=2, RPC_ATTEMPTS=1):
                box = finish_within(lambda: wubook_api.Wubook().__enter__(), 3)
        self.assertNotIn("exc", box, box.get("exc"))
        server, token = box["value"]
        self.assertEqual(token, "tok")
        self.assertIsNotNone(server)

    def test_transient_classification(self):
        self.assertTrue(wubook_api._is_transient(TimeoutError("timed out")))
        self.assertTrue(wubook_api._is_transient(ExpatError("unclosed token")))
        self.assertTrue(wubook_api._is_transient(ConnectionResetError("reset")))
        self.assertTrue(
            wubook_api._is_transient(OSError(101, "Network is unreachable"))
        )
        self.assertTrue(
            wubook_api._is_transient(
                xmlrpc.client.ProtocolError("host", 503, "busy", {})
            )
        )
        self.assertFalse(
            wubook_api._is_transient(
                xmlrpc.client.ProtocolError("host", 404, "missing", {})
            )
        )
        self.assertFalse(wubook_api._is_transient(xmlrpc.client.Fault(1, "nope")))
        self.assertFalse(wubook_api._is_transient(ValueError("bad date")))


if __name__ == "__main__":
    unittest.main()
