"""Scrub credentials from every log record, whichever library emits it.

Provider keys travel as URL parameters (Open-Meteo ``apikey``, Valhalla ``api_key``), and
third-party loggers such as urllib3 print full request URLs (e.g. "Retrying ... /v1/forecast?
...&apikey=..."). A log-record factory redacts them when the record is created, so every
handler (console, Render, pytest) only ever sees the redacted text, tracebacks included.
"""
from __future__ import annotations

import logging
import re

_SECRET = re.compile(r"((?:api_?key|apikey|access_token|token|password|secret)=)[^&\s'\"<>)]+", re.IGNORECASE)
_installed = False


def redact(text: str) -> str:
    return _SECRET.sub(r"\1[REDACTED]", text)


def install() -> None:
    """Install the redacting record factory once per process."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging over a bad format string
            return record
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            if redact(text) != text:
                record.exc_text = redact(text)
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
