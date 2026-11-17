"""Shared HTTP client.

curl_cffi sends requests with a real Chrome TLS/HTTP2 fingerprint, so the sites serve
us the same public pages a normal browser gets. We keep one session per platform so
cookies persist (Myntra's search endpoint needs the cookies its homepage sets).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from curl_cffi import requests

TIMEOUT = 20
_sessions: dict[str, requests.Session] = {}
_lock = threading.Lock()


class FetchError(Exception):
    """Raised when a platform could not be checked (blocked, timeout, 5xx)."""


def session(platform: str) -> requests.Session:
    with _lock:
        s = _sessions.get(platform)
        if s is None:
            s = requests.Session(impersonate="chrome")
            s.headers.update({"Accept-Language": "en-IN,en;q=0.9"})
            _sessions[platform] = s
        return s


def reset_session(platform: str) -> None:
    with _lock:
        _sessions.pop(platform, None)


def get(platform: str, url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None,
        retries: int = 1, expect_json: bool = False):
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = session(platform).get(url, params=params, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code in (401, 403, 429, 503) or r.status_code >= 500:
                raise FetchError(f"{platform} returned HTTP {r.status_code}")
            if expect_json:
                return r, r.json()
            return r, None
        except FetchError as e:
            last = e
        except Exception as e:  # network errors, JSON decode errors
            last = FetchError(f"{platform} request failed: {type(e).__name__}: {e}")
        if attempt < retries:
            reset_session(platform)
            time.sleep(0.8 * (attempt + 1))
    raise last  # type: ignore[misc]
