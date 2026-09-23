"""Polite HTTP fetching: one request at a time per host, with retries."""
import threading
import time
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 phd-radar/1.0")


class Fetcher:
    def __init__(self, delay=2.0, timeout=40):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        self._locks = {}
        self._last = {}
        self._guard = threading.Lock()

    def _host_lock(self, host):
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def get(self, url, delay=None, headers=None, raw=False):
        """Return the page text (or bytes with raw=True). Raises on failure."""
        host = urlparse(url).netloc
        delay = self.delay if delay is None else delay
        err = None
        with self._host_lock(host):
            for attempt in range(3):
                wait = self._last.get(host, 0) + delay - time.time()
                if wait > 0:
                    time.sleep(wait)
                try:
                    r = self.session.get(url, timeout=self.timeout, headers=headers or {})
                    self._last[host] = time.time()
                    if r.status_code in (429, 500, 502, 503, 504):
                        err = f"HTTP {r.status_code}"
                        time.sleep(10 * (attempt + 1))
                        continue
                    if r.status_code >= 400:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    if raw:
                        return r.content
                    enc = (r.encoding or "").lower()
                    if not enc or (enc == "iso-8859-1" and "charset" not in r.headers.get("content-type", "")):
                        r.encoding = r.apparent_encoding
                    elif enc in ("iso-8859-1", "latin-1", "latin1"):
                        r.encoding = "cp1252"  # what sites labelled latin-1 really use (curly quotes)
                    return r.text
                except requests.RequestException as e:
                    self._last[host] = time.time()
                    err = type(e).__name__
                    time.sleep(5 * (attempt + 1))
        raise RuntimeError(err or "fetch failed")
