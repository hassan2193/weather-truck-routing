"""Checkpoint generation and ETA estimation along a route (pure functions)."""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .geometry import LatLon, cumulative_miles, point_at_distance

ALLOWED_INTERVALS = (10, 25, 50)
_EPS = 1e-6


@dataclass(frozen=True)
class CheckpointSpec:
    sequence: int
    distance_mi: float  # distance from origin along the route
    lat: float
    lon: float
    segment_start_mi: float  # stretch of route this checkpoint represents
    segment_end_mi: float

    @property
    def segment_mi(self) -> float:
        return self.segment_end_mi - self.segment_start_mi


def checkpoint_distances(total_miles: float, interval_miles: float) -> list[float]:
    """Distances (miles from origin) at which to sample weather.

    Samples are taken at 0, interval, 2*interval, ... and always at the final
    destination, so the origin and the destination each get a checkpoint.
    """
    if total_miles < 0:
        raise ValueError("total_miles must not be negative")
    if interval_miles <= 0:
        raise ValueError("interval_miles must be positive")
    distances = []
    k = 0
    while k * interval_miles < total_miles - _EPS:
        distances.append(float(k * interval_miles))
        k += 1
    distances.append(float(total_miles))
    return distances


def segment_bounds(distances: Sequence[float]) -> list[tuple[float, float]]:
    """Stretch of road each checkpoint represents.

    A checkpoint covers the road from the midpoint to the previous checkpoint
    up to the midpoint to the next one (clipped to the route ends), so the
    segments tile the route exactly and their lengths sum to the trip distance.
    """
    n = len(distances)
    bounds = []
    for i, d in enumerate(distances):
        start = d if i == 0 else (distances[i - 1] + d) / 2
        end = d if i == n - 1 else (d + distances[i + 1]) / 2
        bounds.append((start, end))
    return bounds


def generate_checkpoints(
    coords: Sequence[LatLon], total_miles: float, interval_miles: float
) -> list[CheckpointSpec]:
    """Place checkpoints on the *actual route geometry*.

    The great-circle length of the polyline can differ slightly from the
    provider's reported road distance, so vertex distances are rescaled to the
    reported total; checkpoint distances therefore agree with the distance
    shown to the user.
    """
    if len(coords) < 2:
        raise ValueError("geometry needs at least two points")
    cum = cumulative_miles(coords)
    if cum[-1] <= 0:
        raise ValueError("geometry has zero length")
    scale = total_miles / cum[-1]
    scaled = [c * scale for c in cum]

    distances = checkpoint_distances(total_miles, interval_miles)
    bounds = segment_bounds(distances)
    specs = []
    for i, (d, (start, end)) in enumerate(zip(distances, bounds)):
        lat, lon = point_at_distance(coords, scaled, d)
        specs.append(CheckpointSpec(i, d, lat, lon, start, end))
    return specs


# ---------------------------------------------------------------------------
# ETA
# ---------------------------------------------------------------------------
class TimeProfile:
    """Cumulative (distance, elapsed time) breakpoints along a route.

    Built from the routing provider's per-maneuver length and duration, so ETAs
    reflect slower urban stretches and faster highway stretches instead of one
    flat average speed. Between breakpoints speed is assumed constant.
    """

    def __init__(self, breakpoints: Sequence[tuple[float, float]]):
        pts = sorted(breakpoints)
        if len(pts) < 2:
            raise ValueError("a time profile needs at least two breakpoints")
        self._dist = [p[0] for p in pts]
        self._time = [p[1] for p in pts]

    @classmethod
    def constant_speed(cls, total_miles: float, total_seconds: float) -> TimeProfile:
        return cls([(0.0, 0.0), (total_miles, total_seconds)])

    @classmethod
    def from_segments(
        cls, segments: Sequence[tuple[float, float]], total_miles: float, total_seconds: float
    ) -> TimeProfile:
        """Build from ``[(length_mi, seconds), ...]`` and rescale to the route totals."""
        dist = time = 0.0
        pts = [(0.0, 0.0)]
        for length, secs in segments:
            dist += length
            time += secs
            pts.append((dist, time))
        if dist <= 0 or time <= 0:
            return cls.constant_speed(total_miles, total_seconds)
        d_scale, t_scale = total_miles / dist, total_seconds / time
        return cls([(d * d_scale, t * t_scale) for d, t in pts])

    @property
    def total_seconds(self) -> float:
        return self._time[-1]

    def elapsed_seconds(self, distance_mi: float) -> float:
        if distance_mi <= self._dist[0]:
            return self._time[0]
        if distance_mi >= self._dist[-1]:
            return self._time[-1]
        i = bisect_right(self._dist, distance_mi) - 1
        span = self._dist[i + 1] - self._dist[i]
        t = 0.0 if span == 0 else (distance_mi - self._dist[i]) / span
        return self._time[i] + (self._time[i + 1] - self._time[i]) * t

    def eta(self, departure: datetime, distance_mi: float) -> datetime:
        return departure + timedelta(seconds=self.elapsed_seconds(distance_mi))

    def to_list(self) -> list[list[float]]:
        return [[round(d, 4), round(t, 2)] for d, t in zip(self._dist, self._time)]

    @classmethod
    def from_list(cls, data: Sequence[Sequence[float]]) -> TimeProfile:
        return cls([(float(d), float(t)) for d, t in data])
