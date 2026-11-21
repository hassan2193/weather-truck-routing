"""Geometry helpers: polyline codec, great-circle distance, positions along a line."""
from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence

LatLon = tuple[float, float]
EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


def decode_polyline(encoded: str, precision: int = 6) -> list[LatLon]:
    """Decode a Google/Valhalla encoded polyline into ``[(lat, lon), ...]``."""
    factor = 10 ** precision
    coords: list[LatLon] = []
    index = lat = lon = 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords


def encode_polyline(coords: Sequence[LatLon], precision: int = 6) -> str:
    factor = 10 ** precision
    out: list[str] = []
    prev_lat = prev_lon = 0
    for lat, lon in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for delta in (ilat - prev_lat, ilon - prev_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


def cumulative_miles(coords: Sequence[LatLon]) -> list[float]:
    """Cumulative great-circle distance (miles) at every vertex; first value is 0."""
    cum = [0.0]
    for prev, cur in zip(coords, coords[1:]):
        cum.append(cum[-1] + haversine_miles(prev, cur))
    return cum


def point_at_distance(coords: Sequence[LatLon], cum: Sequence[float], distance: float) -> LatLon:
    """Interpolate the position ``distance`` miles along the line.

    ``cum`` must come from :func:`cumulative_miles` for the same coordinates
    (optionally scaled). Distances outside ``[0, total]`` are clamped.
    """
    if not coords:
        raise ValueError("empty geometry")
    if distance <= 0 or len(coords) == 1:
        return coords[0]
    if distance >= cum[-1]:
        return coords[-1]
    i = bisect_right(cum, distance) - 1  # cum[i] <= distance < cum[i+1]
    span = cum[i + 1] - cum[i]
    t = 0.0 if span == 0 else (distance - cum[i]) / span
    (lat1, lon1), (lat2, lon2) = coords[i], coords[i + 1]
    return (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)
