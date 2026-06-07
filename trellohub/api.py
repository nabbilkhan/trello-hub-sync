"""A tiny, dependency-free Trello REST client (stdlib only).

Handles auth, retries/backoff, multipart file upload and authenticated file
download. Every call appends ``key`` + ``token`` to the query string.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.trello.com/1"


class TrelloError(RuntimeError):
    pass


class Trello:
    def __init__(self, key: str, token: str):
        self.key = key
        self.token = token
        self._auth_header = f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'

    # -- low level -----------------------------------------------------------
    def _url(self, path: str, params: dict | None = None) -> str:
        q = dict(params or {})
        q["key"] = self.key
        q["token"] = self.token
        sep = "&" if "?" in path else "?"
        return f"{BASE}{path}{sep}{urllib.parse.urlencode(q)}"

    def _request(self, method: str, url: str, data=None, headers=None):
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                body = e.read()[:250].decode("utf-8", "replace")
                raise TrelloError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {body}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise TrelloError(f"{method} {url.split('?')[0]} -> {e}") from e
        raise TrelloError(str(last))

    # -- json helpers --------------------------------------------------------
    def get(self, path: str, **params):
        return json.loads(self._request("GET", self._url(path, params)))

    def post(self, path: str, **data):
        body = urllib.parse.urlencode(data).encode()
        return json.loads(self._request("POST", self._url(path), data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"}))

    def put(self, path: str, **data):
        body = urllib.parse.urlencode(data).encode()
        return json.loads(self._request("PUT", self._url(path), data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"}))

    def delete(self, path: str):
        return self._request("DELETE", self._url(path))

    # -- attachments ---------------------------------------------------------
    def download(self, url: str) -> bytes:
        """Download an attachment that requires Trello auth (uploaded files)."""
        return self._request("GET", url, headers={"Authorization": self._auth_header})

    def upload(self, path: str, filename: str, content: bytes):
        """Multipart POST of a file onto a card's attachments."""
        boundary = "----trellohub" + os.urandom(8).hex()
        pre = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{filename}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body = pre + content + f"\r\n--{boundary}--\r\n".encode()
        return self._request("POST", self._url(path), data=body,
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
