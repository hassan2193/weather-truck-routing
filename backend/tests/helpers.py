"""Builders for fake provider HTTP responses used by the API tests.

The fake Valhalla/Open-Meteo payloads follow the real providers' JSON schemas;
the tests mock only the network layer so the full pipeline (parsing, ETA,
checkpoints, risk, ranking, persistence, serialization) runs for real.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import responses
from django.conf import settings

from routing.geometry import cumulative_miles, encode_polyline

ORIGIN = (41.8781, -87.6298)  # Chicago
DEST = (39.7684, -86.1581)  # Indianapolis


def route_points(bulge_lon: float = 0.0, n: int = 80):
    """Straight line origin->destination, optionally bulging east in the middle."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        lat = ORIGIN[0] + (DEST[0] - ORIGIN[0]) * t
        lon = ORIGIN[1] + (DEST[1] - ORIGIN[1]) * t + bulge_lon * math.sin(math.pi * t)
        pts.append((lat, lon))
    return pts


def valhalla_trip(points, speeds_mph=(30, 60, 55)):
    """A Valhalla ``trip`` dict with three maneuvers of different speeds."""
    total = cumulative_miles(points)[-1]
    third = total / 3
    maneuvers, secs = [], 0.0
    for i, (name, mph) in enumerate(zip(("Main St", "I 65 South", "I 65 South"), speeds_mph)):
        t = third / mph * 3600
        secs += t
        maneuvers.append({"length": third, "time": t, "street_names": [name], "begin_shape_index": i})
    return {
        "summary": {"length": total, "time": secs, "has_toll": False, "has_ferry": False},
        "legs": [{"shape": encode_polyline(points), "maneuvers": maneuvers, "summary": {}}],
    }


def valhalla_body(bulges=(0.0, 1.0, -1.0)):
    trips = [valhalla_trip(route_points(b), speeds_mph=(30, 60 - 5 * i, 55 - 5 * i)) for i, b in enumerate(bulges)]
    body = {"trip": trips[0]}
    if len(trips) > 1:
        body["alternates"] = [{"trip": t} for t in trips[1:]]
    return body


def calm(lat, lon, hour_index):
    return {"wind_speed_10m": 8.0, "wind_gusts_10m": 12.0, "rain": 0.0, "showers": 0.0, "snowfall": 0.0}


def severe_on_route_a(lat, lon, hour_index):
    """48 mph wind in a zone only route A (the straight one) passes through."""
    w = 48.0 if abs(lat - 40.8) < 0.5 and lon < -86.6 else 8.0
    return {**calm(lat, lon, hour_index), "wind_speed_10m": w}


def severe_everywhere(lat, lon, hour_index):
    return {**calm(lat, lon, hour_index), "wind_speed_10m": 48.0}


def open_meteo_callback(weather_fn=calm):
    """responses callback that mimics Open-Meteo's multi-location hourly response."""
    calls = []

    def callback(request):
        q = parse_qs(urlparse(request.url).query)
        lats = [float(x) for x in q["latitude"][0].split(",")]
        lons = [float(x) for x in q["longitude"][0].split(",")]
        past, days = int(q["past_days"][0]), int(q["forecast_days"][0])
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=past)
        n = (past + days) * 24
        calls.append(len(lats))
        out = []
        for lat, lon in zip(lats, lons):
            rows = [weather_fn(lat, lon, i) for i in range(n)]
            hourly = {"time": [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]}
            for key in ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall"):
                hourly[key] = [r[key] for r in rows]
            out.append({"latitude": lat, "longitude": lon, "hourly": hourly})
        body = out if len(out) > 1 else out[0]
        return 200, {}, json.dumps(body)

    callback.calls = calls
    return callback


def install(rsps: responses.RequestsMock, *, valhalla=None, weather=calm, valhalla_status=200):
    """Register fake Valhalla and Open-Meteo endpoints on a ``responses`` mock."""
    rsps.add(
        responses.POST, f"{settings.VALHALLA_URL}/route",
        json=valhalla if valhalla is not None else valhalla_body(), status=valhalla_status,
    )
    cb = open_meteo_callback(weather)
    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=cb, content_type="application/json")
    return cb
