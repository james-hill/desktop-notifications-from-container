import io
import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from notify_server import (
    NotifyHandler,
    _applescript_quote,
    _check_rate_limit,
    _rate_timestamps,
    MAX_TITLE_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_BODY_SIZE,
    RATE_LIMIT,
)


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), NotifyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _post(port, path="/notify", body=None, raw_body=None):
    url = f"http://127.0.0.1:{port}{path}"
    if raw_body is not None:
        data = raw_body
    else:
        data = json.dumps(body).encode() if body is not None else b""
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    return urlopen(req)


def _get(port, path="/health"):
    url = f"http://127.0.0.1:{port}{path}"
    return urlopen(url)


class TestAppleScriptQuote(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(_applescript_quote("hello"), '"hello"')

    def test_quotes(self):
        self.assertEqual(_applescript_quote('say "hi"'), '"say \\"hi\\""')

    def test_backslashes(self):
        self.assertEqual(_applescript_quote("a\\b"), '"a\\\\b"')

    def test_both(self):
        self.assertEqual(_applescript_quote('a\\"b'), '"a\\\\\\"b"')

    def test_empty(self):
        self.assertEqual(_applescript_quote(""), '""')

    def test_unicode(self):
        self.assertEqual(_applescript_quote("hello 🎉"), '"hello 🎉"')


class TestHealthEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health_returns_ok(self):
        resp = _get(self.port, "/health")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read())
        self.assertEqual(body, {"status": "ok"})

    def test_unknown_get_returns_404(self):
        with self.assertRaises(HTTPError) as ctx:
            _get(self.port, "/unknown")
        self.assertEqual(ctx.exception.code, 404)


class TestNotifyEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @patch("notify_server.send_notification")
    def test_valid_notification(self, mock_send):
        resp = _post(self.port, body={"title": "Test", "message": "Hello"})
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read())
        self.assertEqual(body, {"status": "ok"})
        mock_send.assert_called_once_with("Test", "Hello", True)

    @patch("notify_server.send_notification")
    def test_defaults(self, mock_send):
        resp = _post(self.port, body={})
        self.assertEqual(resp.status, 200)
        mock_send.assert_called_once_with("Notification", "", True)

    @patch("notify_server.send_notification")
    def test_sound_false(self, mock_send):
        resp = _post(self.port, body={"title": "T", "message": "M", "sound": False})
        self.assertEqual(resp.status, 200)
        mock_send.assert_called_once_with("T", "M", False)

    def test_invalid_json(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, raw_body=b"not json")
        self.assertEqual(ctx.exception.code, 400)

    def test_empty_body(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, raw_body=b"")
        self.assertEqual(ctx.exception.code, 400)

    def test_wrong_path(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, path="/wrong", body={"title": "T"})
        self.assertEqual(ctx.exception.code, 404)

    def test_title_too_long(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, body={"title": "x" * (MAX_TITLE_LENGTH + 1)})
        self.assertEqual(ctx.exception.code, 400)

    def test_message_too_long(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, body={"message": "x" * (MAX_MESSAGE_LENGTH + 1)})
        self.assertEqual(ctx.exception.code, 400)

    def test_body_too_large(self):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, raw_body=b"x" * (MAX_BODY_SIZE + 1))
        self.assertEqual(ctx.exception.code, 413)

    @patch("notify_server.send_notification", side_effect=RuntimeError("osascript failed"))
    def test_notification_failure_returns_500(self, mock_send):
        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, body={"title": "T", "message": "M"})
        self.assertEqual(ctx.exception.code, 500)
        body = ctx.exception.read().decode()
        self.assertNotIn("osascript failed", body)


class TestAllowSound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @patch("notify_server.send_notification")
    def test_sound_muted_globally(self, mock_send):
        with patch.dict(os.environ, {"ALLOW_SOUND": "off"}):
            resp = _post(self.port, body={"title": "T", "message": "M", "sound": True})
        self.assertEqual(resp.status, 200)
        mock_send.assert_called_once_with("T", "M", False)

    @patch("notify_server.send_notification")
    def test_sound_allowed_by_default(self, mock_send):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLOW_SOUND", None)
            resp = _post(self.port, body={"title": "T", "message": "M"})
        self.assertEqual(resp.status, 200)
        mock_send.assert_called_once_with("T", "M", True)


class TestRateLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @patch("notify_server.send_notification")
    def test_rate_limit_exceeded(self, mock_send):
        _rate_timestamps.clear()
        for _ in range(RATE_LIMIT):
            _post(self.port, body={"title": "T", "message": "M"})

        with self.assertRaises(HTTPError) as ctx:
            _post(self.port, body={"title": "T", "message": "M"})
        self.assertEqual(ctx.exception.code, 429)
        body = json.loads(ctx.exception.read())
        self.assertEqual(body["error"], "Rate limit exceeded")

        _rate_timestamps.clear()


if __name__ == "__main__":
    unittest.main()
