"""Shared HTTP session with retries, used by every outbound provider call.

Retry policy is deliberately bounded so one request can never block a web worker for
minutes (gunicorn and the frontend both give up after 120 s):

* a request that already **timed out is not retried** (``read=0``): it has used its
  whole timeout once, and retrying a stuck provider only multiplies the wait;
* connection failures and 429/502/503/504 are retried at most twice with a short,
  capped backoff, and a provider's ``Retry-After`` header is **not** obeyed (a value
  like 40 s x 3 retries alone exceeds the request budget; we fail fast instead and
  tell the user to retry).
"""
from __future__ import annotations

import threading
import time

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_local = threading.local()


def get_session() -> requests.Session:
    """Thread-local session (requests.Session is not guaranteed thread-safe)."""
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=0,
            status=2,
            backoff_factor=0.5,
            backoff_max=2.0,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=False,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers["User-Agent"] = settings.HTTP_USER_AGENT
        _local.session = session
    return session


CONNECT_TIMEOUT_SECONDS = 5.0


def timeouts(read_seconds: float) -> tuple[float, float]:
    """``(connect, read)`` timeouts: an unreachable host fails within seconds, not the read budget."""
    return (min(CONNECT_TIMEOUT_SECONDS, read_seconds), read_seconds)


class Deadline:
    """Wall-clock budget for one API request that fans out to several providers."""

    def __init__(self, seconds: float):
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def timeout(self, cap: float, reserve: float = 0.0) -> float:
        """Largest timeout <= ``cap`` that still leaves ``reserve`` seconds for later steps."""
        return max(0.0, min(cap, self.remaining() - reserve))
