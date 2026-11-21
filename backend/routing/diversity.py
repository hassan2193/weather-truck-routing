"""Route distinctness checks (pure geometry, no I/O).

Two routes count as the *same* route when almost all of one lies close to the other,
even if their coordinates differ slightly (parallel carriageways, a frontage road, a
different ramp, polyline noise). We measure, for a candidate route, the share of its
length that lies farther than ``tolerance_mi`` from a reference route; a candidate is
genuinely distinct only if that unique share is large enough against *every* route
already accepted.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geometry import LatLon, cumulative_miles, haversine_miles, point_at_distance

MILES_PER_DEG_LAT = 69.0

# A candidate must leave every accepted route for at least this share of its length...
MIN_UNIQUE_FRACTION = 0.15
# ...and for at least this many miles (guards very short trips).
MIN_UNIQUE_MILES = 2.0
# Points closer than this to the other route are "the same road" (covers carriageways,
# frontage roads and ramps, which sit well within half a mile of each other).
TOLERANCE_MI = 0.5


def resample(coords: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Points every ``step_mi`` miles along the line (plus the end point)."""
    if len(coords) < 2:
        return list(coords)
    cum = cumulative_miles(coords)
    total = cum[-1]
    n = max(1, int(total // step_mi))
    pts = [point_at_distance(coords, cum, i * step_mi) for i in range(n + 1)]
    if total - n * step_mi > 1e-9:
        pts.append(coords[-1])
    return pts


class _Index:
    """Grid index over a densely resampled reference route, in local planar miles."""

    def __init__(self, coords: Sequence[LatLon], tolerance_mi: float, lat0: float):
        self._kx = MILES_PER_DEG_LAT * math.cos(math.radians(lat0))
        self._cell = tolerance_mi
        self._tol2 = tolerance_mi * tolerance_mi
        self._grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
        # sample at <= tolerance/4 so point spacing barely affects the distance test
        for lat, lon in resample(coords, tolerance_mi / 4):
            x, y = lon * self._kx, lat * MILES_PER_DEG_LAT
            self._grid.setdefault((int(x // self._cell), int(y // self._cell)), []).append((x, y))

    def near(self, lat: float, lon: float) -> bool:
        x, y = lon * self._kx, lat * MILES_PER_DEG_LAT
        cx, cy = int(x // self._cell), int(y // self._cell)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for px, py in self._grid.get((gx, gy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 <= self._tol2:
                        return True
        return False


def unique_fraction(
    candidate: Sequence[LatLon], reference: Sequence[LatLon], tolerance_mi: float = TOLERANCE_MI
) -> float:
    """Share (0-1) of ``candidate``'s length lying more than ``tolerance_mi`` from ``reference``."""
    if len(candidate) < 2:
        return 0.0
    lat0 = (candidate[0][0] + candidate[-1][0]) / 2
    index = _Index(reference, tolerance_mi, lat0)
    samples = resample(candidate, tolerance_mi)
    far = sum(1 for lat, lon in samples if not index.near(lat, lon))
    return far / len(samples)


@dataclass(frozen=True)
class Distinctness:
    distinct: bool
    unique_fraction: float  # smallest unique share against any accepted route
    unique_miles: float


def compare(
    candidate: Sequence[LatLon],
    candidate_miles: float,
    accepted: Sequence[Sequence[LatLon]],
    *,
    min_fraction: float = MIN_UNIQUE_FRACTION,
    min_miles: float = MIN_UNIQUE_MILES,
    tolerance_mi: float = TOLERANCE_MI,
) -> Distinctness:
    """Is ``candidate`` genuinely different from every route in ``accepted``?"""
    if not accepted:
        return Distinctness(True, 1.0, candidate_miles)
    worst = min(unique_fraction(candidate, ref, tolerance_mi) for ref in accepted)
    miles = worst * candidate_miles
    return Distinctness(worst >= min_fraction and miles >= min_miles, worst, miles)


# ---------------------------------------------------------------------------
# Avoidance polygons for re-routing
# ---------------------------------------------------------------------------
# Valhalla rejects requests whose exclude_polygons exceed a total circumference
# (10 km on the public FOSSGIS server: error 167). Stay safely below it.
POLYGON_BUDGET_KM = 9.0
MAX_BLOCK_RADIUS_KM = 0.4
MIN_BLOCK_RADIUS_KM = 0.12
# Never block close to the trip's endpoints, or the origin/destination becomes unreachable.
ENDPOINT_CLEARANCE_MI = 3.0
_POLYGON_SIDES = 12


def _ring(lat: float, lon: float, radius_km: float) -> list[list[float]]:
    """Closed 12-sided ring of ``[lon, lat]`` around a point (Valhalla's ring format)."""
    dlat = radius_km / 110.574
    dlon = radius_km / (111.320 * math.cos(math.radians(lat)))
    ring = []
    for i in range(_POLYGON_SIDES + 1):
        a = 2 * math.pi * i / _POLYGON_SIDES
        ring.append([round(lon + dlon * math.cos(a), 6), round(lat + dlat * math.sin(a), 6)])
    return ring


def ring_circumference_km(ring: Sequence[Sequence[float]]) -> float:
    return sum(
        haversine_miles((a[1], a[0]), (b[1], b[0])) * 1.609344 for a, b in zip(ring, ring[1:])
    )


def avoidance_polygons(
    routes: Sequence[Sequence[LatLon]],
    fractions: Sequence[float],
    origin: LatLon,
    destination: LatLon,
    *,
    budget_km: float = POLYGON_BUDGET_KM,
) -> list[list[list[float]]]:
    """Small "road blocks" placed on each given route at the given fractions of its length.

    Blocking a route at several points makes the router leave that corridor and look
    for a genuinely different path, while each block is small enough to stay within
    the provider's polygon limit. Points near the origin or destination are skipped.
    Returns an empty list when nothing can be placed safely.
    """
    centres: list[LatLon] = []
    for coords in routes:
        if len(coords) < 2:
            continue
        cum = cumulative_miles(coords)
        for f in fractions:
            p = point_at_distance(coords, cum, cum[-1] * f)
            if min(haversine_miles(p, origin), haversine_miles(p, destination)) >= ENDPOINT_CLEARANCE_MI:
                centres.append(p)
    if not centres:
        return []
    # circumference of a 12-gon is 2 * n * r * sin(pi / n) ~= 6.21 r; +3% covers the
    # flat-earth degree conversion in _ring so the budget is never exceeded.
    per_unit = 2 * _POLYGON_SIDES * math.sin(math.pi / _POLYGON_SIDES) * 1.03
    radius = min(MAX_BLOCK_RADIUS_KM, budget_km / (len(centres) * per_unit))
    if radius < MIN_BLOCK_RADIUS_KM:
        # too many blocks for the budget: keep the most spread-out subset
        keep = max(1, int(budget_km / (MIN_BLOCK_RADIUS_KM * per_unit)))
        step = len(centres) / keep
        centres = [centres[int(i * step)] for i in range(keep)]
        radius = min(MAX_BLOCK_RADIUS_KM, budget_km / (len(centres) * per_unit))
    return [_ring(lat, lon, radius) for lat, lon in centres]
