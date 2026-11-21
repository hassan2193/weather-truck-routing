"""US National Weather Service (api.weather.gov) as a fallback forecast provider.

Used only for points inside the United States when Open-Meteo could not deliver data.
weather.gov needs no API key but asks for a descriptive User-Agent with contact details.

Request flow (as documented by weather.gov):
1. ``GET /points/{lat},{lon}``    -> the forecast office and grid cell for the point
2. ``GET /gridpoints/{wfo}/{x},{y}`` -> raw forecast layers for that ~2.5 km grid cell

Gridpoint layers are run-length encoded intervals ("2026-11-21T09:00:00+00:00/PT4H").
They are converted into the same :class:`HourlySeries` Open-Meteo produces:

* wind / gusts: km/h -> mph, value of the interval containing the slot time;
* rain: ``quantitativePrecipitation`` (liquid-equivalent, mm over 1-6 h) -> the average
  in/hr over its interval, applied to the hour that *ends* at each slot (same convention
  as Open-Meteo);
* snow: ``snowfallAmount`` (mm of snow over the interval) -> average in/hr likewise.

Hours with no forecast value stay ``None`` (shown as unavailable); nothing is invented.
Because weather.gov precipitation is a multi-hour total, the hourly rate is an average
over that period and can understate a short, intense burst.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from config.http import get_session, timeouts

from .series import HourlySeries

logger = logging.getLogger(__name__)

PROVIDER_NAME = "US National Weather Service (weather.gov)"
POINT_CACHE_TTL = 24 * 3600  # weather.gov allows caching /points for a day (s-maxage=86400)
GRID_CACHE_TTL = 3600  # gridpoint data: max-age=3600
REQUEST_TIMEOUT_S = 10.0
MAX_WORKERS = 4
KMH_TO_MPH = 1 / 1.609344
MM_TO_IN = 1 / 25.4
_NOT_COVERED = "not-covered"

# Coarse bounding boxes of the areas weather.gov forecasts for. They are only a pre-filter:
# points outside are never sent; points inside but not covered (the lower-48 box also spans
# parts of southern Canada and northern Mexico) get weather.gov's 404, which is cached.
US_BOXES = (
    (24.4, 49.5, -125.0, -66.8),  # contiguous US
    (51.0, 71.6, -170.0, -129.9),  # Alaska
    (18.8, 22.4, -160.4, -154.6),  # Hawaii
    (17.5, 18.7, -67.4, -64.5),  # Puerto Rico & US Virgin Islands
)


class NwsError(Exception):
    """weather.gov could not provide data for a request."""


def in_us_bounds(lat: float, lon: float) -> bool:
    """Could weather.gov cover this point? (pre-filter; weather.gov's /points has the final say)"""
    return any(s <= lat <= n and w <= lon <= e for s, n, w, e in US_BOXES)


# ---------------------------------------------------------------------------
# interval parsing
# ---------------------------------------------------------------------------
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def parse_interval(valid_time: str) -> tuple[datetime, timedelta]:
    """'2026-11-21T09:00:00+00:00/PT4H' -> (start UTC, duration)."""
    start_s, dur_s = valid_time.split("/")
    m = _DURATION.match(dur_s)
    if not m or not any(m.groups()):
        raise ValueError(f"unsupported duration {dur_s!r}")
    days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    start = datetime.fromisoformat(start_s).astimezone(UTC)
    return start, timedelta(days=days, hours=hours, minutes=minutes)


def _intervals(layer: dict | None) -> list[tuple[datetime, datetime, float]]:
    """``[(start, end, value)]`` for every interval that has a value (nulls are skipped)."""
    out = []
    for item in (layer or {}).get("values", []):
        if item.get("value") is None:
            continue
        start, dur = parse_interval(item["validTime"])
        out.append((start, start + dur, float(item["value"])))
    return out


def _value_at(intervals, when: datetime):
    for start, end, value in intervals:
        if start <= when < end:
            return value
    return None


def _rate_at(layer: dict | None, when: datetime) -> float | None:
    """Average in/hr of the precipitation interval containing ``when`` (mm total -> in/hr)."""
    for item in (layer or {}).get("values", []):
        if item.get("value") is None:
            continue
        start, dur = parse_interval(item["validTime"])
        if start <= when < start + dur:
            hours = dur.total_seconds() / 3600
            return float(item["value"]) * MM_TO_IN / hours if hours > 0 else None
    return None


def parse_gridpoint(props: dict) -> HourlySeries:
    """Convert weather.gov gridpoint ``properties`` into an hourly series (UTC)."""
    start, span = parse_interval(props["validTimes"])
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = int(span.total_seconds() // 3600)
    wind_iv = _intervals(props.get("windSpeed"))
    gust_iv = _intervals(props.get("windGust"))

    def mph(v):
        return None if v is None else round(v * KMH_TO_MPH, 2)

    def inches(v):
        return None if v is None else round(v, 4)

    wind, gust, rain, snow = [], [], [], []
    for i in range(hours + 1):
        t = start + timedelta(hours=i)
        wind.append(mph(_value_at(wind_iv, t)))
        gust.append(mph(_value_at(gust_iv, t)))
        hour_before = t - timedelta(hours=1)  # slot t reports the hour ending at t
        rain.append(inches(_rate_at(props.get("quantitativePrecipitation"), hour_before)))
        snow.append(inches(_rate_at(props.get("snowfallAmount"), hour_before)))
    return HourlySeries(start=start, wind=wind, gust=gust, rain=rain, snow=snow)


# ---------------------------------------------------------------------------
# HTTP (cached)
# ---------------------------------------------------------------------------
def _get(path: str, timeout: float) -> requests.Response:
    try:
        return get_session().get(
            f"{settings.NWS_URL}{path}",
            headers={"Accept": "application/geo+json", "User-Agent": settings.NWS_USER_AGENT},
            timeout=timeouts(timeout),
        )
    except requests.RequestException as exc:
        raise NwsError(f"weather.gov could not be reached ({type(exc).__name__})") from exc


def grid_for_point(lat: float, lon: float, timeout: float = REQUEST_TIMEOUT_S) -> str | None:
    """'OKX/33,42' for a US point, or None if weather.gov has no forecast there (cached)."""
    key = f"nws:pt:{lat:.4f}:{lon:.4f}"
    cached = cache.get(key)
    if cached is not None:
        return None if cached == _NOT_COVERED else cached
    resp = _get(f"/points/{lat:.4f},{lon:.4f}", timeout)
    if resp.status_code == 404:
        cache.set(key, _NOT_COVERED, POINT_CACHE_TTL)
        return None
    if resp.status_code != 200:
        raise NwsError(f"weather.gov /points error (HTTP {resp.status_code})")
    try:
        p = resp.json()["properties"]
        grid = f"{p['gridId']}/{int(p['gridX'])},{int(p['gridY'])}"
    except (ValueError, KeyError, TypeError) as exc:
        raise NwsError("weather.gov /points returned an unexpected response") from exc
    cache.set(key, grid, POINT_CACHE_TTL)
    return grid


def gridpoint_series(grid: str, timeout: float = REQUEST_TIMEOUT_S) -> HourlySeries:
    key = f"nws:grid:{grid}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    resp = _get(f"/gridpoints/{grid}", timeout)
    if resp.status_code != 200:
        raise NwsError(f"weather.gov gridpoint error (HTTP {resp.status_code})")
    try:
        series = parse_gridpoint(resp.json()["properties"])
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise NwsError("weather.gov gridpoint returned an unexpected response") from exc
    cache.set(key, series, GRID_CACHE_TTL)
    return series


# ---------------------------------------------------------------------------
# fallback for many points
# ---------------------------------------------------------------------------
@dataclass
class NwsResult:
    series: dict[tuple[float, float], HourlySeries] = field(default_factory=dict)
    not_us: int = 0  # outside weather.gov coverage (never requested or 404)
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def fetch_points(points: list[tuple[float, float]], budget_s: float) -> NwsResult:
    """Real weather.gov forecasts for each US point; others are left out (unavailable).

    Stops starting new requests once ``budget_s`` is spent so the analysis deadline holds.
    """
    result = NwsResult()
    started = time.monotonic()
    lock = threading.Lock()
    us_points = [p for p in points if in_us_bounds(*p)]
    result.not_us = len(points) - len(us_points)

    def remaining() -> float:
        return budget_s - (time.monotonic() - started)

    def note_error(msg: str):
        with lock:
            if msg not in result.errors:
                result.errors.append(msg)

    def map_point(p):
        if remaining() <= 1:
            return p, None, "time budget exhausted"
        try:
            return p, grid_for_point(*p, timeout=min(REQUEST_TIMEOUT_S, remaining())), None
        except NwsError as exc:
            return p, None, str(exc)

    grids: dict[str, list[tuple[float, float]]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for p, grid, err in pool.map(map_point, us_points):
            if err:
                result.failed += 1
                note_error(err)
            elif grid is None:
                result.not_us += 1  # inside the box but not covered (e.g. Canada near the border)
            else:
                grids.setdefault(grid, []).append(p)

    def load_grid(grid):
        if remaining() <= 1:
            return grid, None, "time budget exhausted"
        try:
            return grid, gridpoint_series(grid, timeout=min(REQUEST_TIMEOUT_S, remaining())), None
        except NwsError as exc:
            return grid, None, str(exc)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for grid, series, err in pool.map(load_grid, list(grids)):
            if err:
                result.failed += len(grids[grid])
                note_error(err)
                continue
            for p in grids[grid]:
                result.series[p] = series
    if result.errors:
        logger.warning("weather.gov fallback: %d point(s) failed: %s", result.failed, "; ".join(result.errors))
    return result
