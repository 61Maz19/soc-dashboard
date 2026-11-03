"""Forward alerts from the internal network to Telegram. Send only, never read."""
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
MAX_BODY = 4096
MAX_TEXT = 500

SCHEME = re.compile(r"(?i)\bhttp(s?)://")
DOT = re.compile(r"(?<=[A-Za-z0-9-])\.(?=[A-Za-z0-9-])")


def defang(text):
    """Make links, domains and IPs unclickable: http://a.b -> hxxp://a[.]b"""
    return DOT.sub("[.]", SCHEME.sub(r"hxxp\1://", text))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notifier")


def send(text):
    """Send plain text to the configured chat. Retry 3 times."""
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": defang(text)[:MAX_TEXT],
        "link_preview_options": json.dumps({"is_disabled": True}),
    }).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(API_URL, data=data, timeout=10) as resp:
                return resp.status == 200
        except OSError as err:
            # Never log err itself: the token is inside the URL
            log.warning("Send failed (attempt %d): %s", attempt + 1, err.__class__.__name__)
            time.sleep(2 ** attempt)
    return False


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/notify":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                self.send_error(413)
                return
            text = json.loads(self.rfile.read(length))["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty text")
        except (ValueError, KeyError, TypeError):
            self.send_error(400)
            return
        ok = send(text)
        self.send_response(202 if ok else 502)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
