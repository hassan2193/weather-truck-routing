"""Shared HTTP session with retries, used by every outbound provider call."""
from __future__ import annotations

import threading

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
            total=3,
            backoff_factor=0.7,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers["User-Agent"] = settings.HTTP_USER_AGENT
        _local.session = session
    return session
