"""
HTTP server that receives notification requests from Docker containers
and displays them on the host desktop.

Supports macOS (osascript), Linux (notify-send), and Windows (PowerShell).

Default port: 6789 (set via DESKTOP_NOTIFY_PORT env var)
Sound: on by default (set ALLOW_SOUND=off to mute globally)

Usage:
    python notify_server.py

Sample curl call:
    curl -X POST http://localhost:6789/notify \
        -H "Content-Type: application/json" \
        -d '{"title":"Build Complete","message":"Your build has finished","sound":true}'
"""

import json
import os
import signal
import subprocess
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

VERSION = "0.1.0"
MAX_TITLE_LENGTH = 256
MAX_MESSAGE_LENGTH = 4096
MAX_BODY_SIZE = 8192
RATE_LIMIT = 10  # max notifications per second
_rate_lock = threading.Lock()
_rate_timestamps: list[float] = []


def send_notification(title: str, message: str, sound: bool = True) -> None:
    if sys.platform == "darwin":
        _notify_macos(title, message, sound)
    elif sys.platform == "linux":
        _notify_linux(title, message)
    elif sys.platform == "win32":
        _notify_windows(title, message, sound)
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _notify_macos(title: str, message: str, sound: bool) -> None:
    script = f'display notification {_applescript_quote(message)} with title {_applescript_quote(title)}'
    if sound:
        script += ' sound name "default"'
    subprocess.run(["osascript", "-e", script], check=True, timeout=10)


def _notify_linux(title: str, message: str) -> None:
    subprocess.run(["notify-send", title, message], check=True, timeout=10)


def _notify_windows(title: str, message: str, sound: bool) -> None:
    # Uses built-in .NET via PowerShell — no extra modules needed
    ps_title = title.replace("'", "''")
    ps_message = message.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(5000, '{ps_title}', '{ps_message}', 'Info')
"""
    if sound:
        script += "[System.Media.SystemSounds]::Asterisk.Play()\n"
    script += "Start-Sleep -Seconds 6; $n.Dispose()\n"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True, timeout=15,
    )


def _applescript_quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _check_rate_limit() -> bool:
    now = time.monotonic()
    with _rate_lock:
        _rate_timestamps[:] = [t for t in _rate_timestamps if now - t < 1.0]
        if len(_rate_timestamps) >= RATE_LIMIT:
            return False
        _rate_timestamps.append(now)
        return True


def _json_response(handler: "NotifyHandler", code: int, body: dict) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps(body).encode())


class NotifyHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/notify":
            self.send_error(404, "Not Found")
            return

        raw = self.headers.get("Content-Length", "")
        try:
            content_length = int(raw)
        except ValueError:
            self.send_error(400, "Invalid or missing Content-Length")
            return

        if content_length == 0:
            self.send_error(400, "Empty body")
            return

        if content_length > MAX_BODY_SIZE:
            self.send_error(413, f"Body too large (max {MAX_BODY_SIZE} bytes)")
            return

        try:
            body = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        title = body.get("title", "Notification")
        message = body.get("message", "")

        if len(title) > MAX_TITLE_LENGTH:
            self.send_error(400, f"Title too long (max {MAX_TITLE_LENGTH} chars)")
            return
        if len(message) > MAX_MESSAGE_LENGTH:
            self.send_error(400, f"Message too long (max {MAX_MESSAGE_LENGTH} chars)")
            return

        if not _check_rate_limit():
            _json_response(self, 429, {"error": "Rate limit exceeded"})
            return

        sound_allowed = os.environ.get("ALLOW_SOUND", "on").lower() != "off"
        sound = sound_allowed and body.get("sound", True)

        try:
            send_notification(title, message, sound)
        except Exception:
            print(f"[notify-server] ERROR: notification failed", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            self.send_error(500, "Notification failed")
            return

        _json_response(self, 200, {"status": "ok"})

    def do_GET(self) -> None:
        if self.path == "/health":
            _json_response(self, 200, {"status": "ok"})
            return
        self.send_error(404, "Not Found")

    def log_message(self, format: str, *args: object) -> None:
        print(f"[notify-server] {format % args}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        print(f"desktop-notify-server {VERSION}")
        sys.exit(0)

    port = int(os.environ.get("DESKTOP_NOTIFY_PORT", "6789"))
    server = HTTPServer(("127.0.0.1", port), NotifyHandler)

    def shutdown(signum: int, frame: object) -> None:
        print("\nShutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"[notify-server] v{VERSION} listening on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
