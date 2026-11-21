"""Per-route risk metrics computed from checkpoint segments."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from risk_engine.levels import RiskLevel


@dataclass(frozen=True)
class Segment:
    """The stretch of road one checkpoint represents, and its risk (None = no weather data)."""

    miles: float
    level: RiskLevel | None


@dataclass(frozen=True)
class RouteMetrics:
    distance_mi: float
    duration_s: float
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float
    average_risk: float | None  # distance-weighted mean of the 0-4 risk score over assessed miles

    @property
    def assessed_miles(self) -> float:
        return sum(self.miles_by_level.values())

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]

    @property
    def moderate_miles(self) -> float:
        return self.miles_by_level[RiskLevel.MODERATE]

    @property
    def low_miles(self) -> float:
        return self.miles_by_level[RiskLevel.LOW]

    @property
    def has_no_travel(self) -> bool:
        return self.no_travel_miles > 0

    @property
    def coverage(self) -> float:
        """Fraction (0-1) of the route's distance that has weather data."""
        total = self.assessed_miles + self.unknown_miles
        return 1.0 if total <= 0 else self.assessed_miles / total


def compute_metrics(segments: Sequence[Segment], distance_mi: float, duration_s: float) -> RouteMetrics:
    """Aggregate checkpoint segments into risk miles.

    Risk miles use the real length each checkpoint represents (not a checkpoint
    count), so a 50-mile interval and a 10-mile interval give comparable
    numbers. Segments without weather are tracked separately as ``unknown``
    rather than being counted as Low.
    """
    miles = {level: 0.0 for level in RiskLevel}
    unknown = 0.0
    for seg in segments:
        if seg.level is None:
            unknown += seg.miles
        else:
            miles[seg.level] += seg.miles
    assessed = sum(miles.values())
    avg = None if assessed <= 0 else sum(int(lvl) * m for lvl, m in miles.items()) / assessed
    return RouteMetrics(distance_mi, duration_s, miles, unknown, avg)
