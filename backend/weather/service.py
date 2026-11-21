"""Weather lookup for many route points with de-duplication, caching and batching.

Efficiency strategy
-------------------
* Coordinates are snapped to a coarse grid (``WEATHER_GRID_DEGREES``, default
  0.05 deg ~ 3.5 mi). That is finer than the underlying forecast models, and it
  makes nearby points - and points shared by alternative routes along the
  same highway - collapse into a single upstream location.
* Each unique grid cell is fetched **once** as a full hourly series covering the
  whole trip, so every checkpoint ETA, the heatmap and the 48-hour slider all
  reuse the same data.
* Series are cached (default 30 min). Only cache misses are sent to
  Open-Meteo, in batches fetched in parallel.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.cache import cache

from .open_meteo import WeatherProviderError, fetch_batch
from .series import HourlySeries

logger = logging.getLogger(__name__)

GridKey = tuple[float, float]


@dataclass
class WeatherLookup:
    """Result of resolving series for a list of points."""

    series: list[HourlySeries | None]  # parallel to the input points; None = failed
    unique_locations: int = 0
    cache_hits: int = 0
    upstream_requests: int = 0
    failed_locations: int = 0
    errors: list[str] = field(default_factory=list)


def snap(lat: float, lon: float, grid: float | None = None) -> GridKey:
    g = grid or settings.WEATHER_GRID_DEGREES
    return (round(round(lat / g) * g, 4), round(round(lon / g) * g, 4))


def forecast_days_needed(needed_until: datetime, now: datetime | None = None) -> int:
    """Days of forecast (counted from today, UTC) needed to cover ``needed_until``."""
    now = now or datetime.now(UTC)
    days = math.ceil((needed_until - now).total_seconds() / 86400) + 1
    return max(3, min(settings.WEATHER_MAX_FORECAST_DAYS, days))


def _cache_key(key: GridKey) -> str:
    return f"wx:{key[0]:.4f}:{key[1]:.4f}"


def get_series(points: Sequence[tuple[float, float]], needed_until: datetime) -> WeatherLookup:
    """Resolve an hourly series for each point, covering at least up to ``needed_until``."""
    keys = [snap(lat, lon) for lat, lon in points]
    unique = list(dict.fromkeys(keys))
    resolved: dict[GridKey, HourlySeries] = {}
    horizon_cap = datetime.now(UTC) + timedelta(days=settings.WEATHER_MAX_FORECAST_DAYS - 1)
    target = min(needed_until, horizon_cap)

    missing: list[GridKey] = []
    hits = 0
    for key in unique:
        cached = cache.get(_cache_key(key))
        if cached is not None and cached.end >= target:
            resolved[key] = cached
            hits += 1
        else:
            missing.append(key)

    lookup = WeatherLookup(series=[], unique_locations=len(unique), cache_hits=hits)
    if missing:
        days = forecast_days_needed(needed_until)
        batch_size = settings.WEATHER_BATCH_SIZE
        batches = [missing[i : i + batch_size] for i in range(0, len(missing), batch_size)]
        lookup.upstream_requests = len(batches)

        def run(batch: list[GridKey]):
            try:
                return batch, fetch_batch(batch, days), None
            except WeatherProviderError as exc:
                return batch, None, str(exc)

        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            for batch, result, error in pool.map(run, batches):
                if error:
                    logger.warning("Weather batch of %d locations failed: %s", len(batch), error)
                    lookup.errors.append(error)
                    lookup.failed_locations += len(batch)
                    continue
                for key, series in zip(batch, result):
                    resolved[key] = series
                    cache.set(_cache_key(key), series, settings.WEATHER_CACHE_TTL_SECONDS)

    lookup.series = [resolved.get(k) for k in keys]
    return lookup
