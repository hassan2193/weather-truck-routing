"""Forecast corridor data for the heatmap and the 0-48 hour slider.

For a stored route this returns, for every checkpoint and for a denser set of
corridor sample points, the hourly wind / rain / snow and the resulting risk
level for each of the 49 hours starting at the departure hour. All values come
from the weather provider (cached series reused from the analysis); risk is
computed with the same rules as the checkpoint engine so the frontend never
re-implements classification.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.core.cache import cache

from risk_engine.rules import assess
from weather.series import HourlySeries, floor_to_hour, sample_series, slot_sample
from weather.service import get_series

from .checkpoints import TimeProfile, checkpoint_distances
from .geometry import cumulative_miles, decode_polyline, point_at_distance
from .models import Route

FORECAST_HOURS = 48
HEAT_MIN_SPACING_MI = 10.0
HEAT_MAX_POINTS = 120
CACHE_TTL = 600


def heat_distances(total_miles: float) -> list[float]:
    spacing = max(HEAT_MIN_SPACING_MI, total_miles / HEAT_MAX_POINTS)
    return checkpoint_distances(total_miles, spacing)


def _risk(sample, load_lb: float) -> int | None:
    if not sample.available:
        return None
    a = assess(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, load_lb)
    return None if a is None else int(a.level)


def _round(v: float | None, nd: int) -> float | None:
    return None if v is None else round(v, nd)


def _hourly(series: HourlySeries | None, first_index: int, load_lb: float) -> dict:
    wind, rain, snow, risk = [], [], [], []
    for h in range(FORECAST_HOURS + 1):
        s = slot_sample(series, first_index + h)
        wind.append(_round(s.wind_mph, 1) if s.available else None)
        rain.append(_round(s.rain_in_hr, 3) if s.available else None)
        snow.append(_round(s.snow_in_hr, 3) if s.available else None)
        risk.append(_risk(s, load_lb))
    return {"wind": wind, "rain": rain, "snow": snow, "risk": risk}


def build_route_forecast(route: Route) -> dict:
    """Return the forecast payload for ``route`` (cached briefly)."""
    cache_key = f"forecast:{route.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    analysis = route.analysis
    load = analysis.load_weight_lb
    departure = analysis.departure_time
    base = floor_to_hour(departure)
    profile = TimeProfile.from_list(route.time_profile)
    coords = decode_polyline(route.geometry)
    cum = cumulative_miles(coords)
    scale = route.distance_mi / cum[-1] if cum[-1] else 1.0
    cum = [c * scale for c in cum]

    checkpoints = list(route.checkpoints.all())
    heat = [(d, *point_at_distance(coords, cum, d)) for d in heat_distances(route.distance_mi)]

    points = [(c.lat, c.lon) for c in checkpoints] + [(lat, lon) for _, lat, lon in heat]
    needed_until = max(base + timedelta(hours=FORECAST_HOURS + 1), route.arrival_time + timedelta(hours=1))
    lookup = get_series(points, needed_until)

    series_iter = iter(lookup.series)
    cp_payload = []
    for c in checkpoints:
        series = next(series_iter)
        first = _slot_index(series, base)
        cp_payload.append({"id": c.sequence, **_hourly(series, first, load)})

    heat_payload = []
    for d, lat, lon in heat:
        series = next(series_iter)
        eta = profile.eta(departure, d)
        eta_sample = sample_series(series, eta)
        first = _slot_index(series, base)
        heat_payload.append({
            "lat": round(lat, 5), "lon": round(lon, 5), "distance_mi": round(d, 2), "eta": eta.isoformat(),
            "eta_wind": _round(eta_sample.wind_mph, 1) if eta_sample.available else None,
            "eta_rain": _round(eta_sample.rain_in_hr, 3) if eta_sample.available else None,
            "eta_snow": _round(eta_sample.snow_in_hr, 3) if eta_sample.available else None,
            "eta_risk": _risk(eta_sample, load),
            **_hourly(series, first, load),
        })

    payload = {
        "route_id": str(route.id),
        "start": base.isoformat(),
        "hours": [(base + timedelta(hours=h)).isoformat() for h in range(FORECAST_HOURS + 1)],
        "checkpoints": cp_payload,
        "heat": heat_payload,
        "stats": {
            "unique_locations": lookup.unique_locations,
            "cache_hits": lookup.cache_hits,
            "upstream_requests": lookup.upstream_requests,
            "failed_locations": lookup.failed_locations,
            "errors": list(dict.fromkeys(lookup.errors))[:3],
            "fallback_provider": lookup.fallback_provider,
            "fallback_locations": lookup.fallback_locations,
        },
    }
    if not lookup.failed_locations:  # never cache a degraded result
        cache.set(cache_key, payload, CACHE_TTL)
    return payload


def _slot_index(series: HourlySeries | None, when: datetime) -> int:
    """Index of the hourly slot at ``when`` within ``series`` (may be out of range)."""
    if series is None:
        return 0
    return int(round((when - series.start).total_seconds() / 3600))
