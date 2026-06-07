"""Optional real-time receiver.

Trello calls this on every board action; we debounce a burst into one sync run.
We never trust the payload — the engine re-derives all state from the API, so a
spurious or forged trigger is at worst a harmless no-op run. The 30-minute poll
timer backstops anything missed (e.g. while the public endpoint is down).

Run it behind any HTTPS reverse proxy / tunnel that forwards to this localhost
port + secret path (see docs/WEBHOOKS.md). Set ``[receiver].path`` to a secret
value (``openssl rand -hex 16``) and ``[receiver].public_url`` to the HTTPS URL.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import comments, engine

DEBOUNCE_SEC = 2.5
RELEVANT = re.compile(r"card|member", re.IGNORECASE)
SYNCED = "⟦synced:"


def serve(cfg):
    log = engine.make_logger(cfg)
    wake = threading.Event()

    def worker():
        while True:
            wake.wait()
            time.sleep(DEBOUNCE_SEC)   # let a burst settle
            wake.clear()
            try:
                c = engine.run(cfg)
                log(f"realtime sync: {c}")
            except Exception as e:  # noqa: BLE001
                log(f"sync ERROR: {e!r}")

    def valid(body, sig):
        if not cfg.api_secret or not cfg.receiver_public_url:
            return True  # signature verification not configured -> accept
        if not sig:
            return False
        mac = hmac.new(cfg.api_secret.encode(), body + cfg.receiver_public_url.encode(), hashlib.sha1)
        return hmac.compare_digest(base64.b64encode(mac.digest()).decode(), sig)

    class Handler(BaseHTTPRequestHandler):
        def _ok(self, code=200):
            self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()

        def log_message(self, *a):
            pass

        def do_HEAD(self):
            self._ok(200 if self.path == cfg.receiver_path else 404)

        def do_GET(self):
            self._ok(200 if self.path == cfg.receiver_path else 404)

        def do_POST(self):
            if self.path != cfg.receiver_path:
                self._ok(404); return
            n = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(n) if n else b""
            self._ok(200)  # answer fast so Trello never disables the webhook
            if not valid(body, self.headers.get("X-Trello-Webhook", "")):
                log("REJECTED: bad/missing HMAC signature"); return
            try:
                act = (json.loads(body or b"{}").get("action", {}) or {})
                atype = act.get("type", "")
                ctext = (act.get("data", {}) or {}).get("text", "") or ""
            except ValueError:
                atype, ctext = "", ""
            if atype == "commentCard":
                if SYNCED not in ctext:
                    threading.Thread(target=comments.route, args=(cfg, body), daemon=True).start()
                return
            if atype == "" or RELEVANT.search(atype):
                wake.set()

    threading.Thread(target=worker, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", cfg.receiver_port), Handler)
    log(f"receiver listening on 127.0.0.1:{cfg.receiver_port} path={cfg.receiver_path}")
    httpd.serve_forever()
