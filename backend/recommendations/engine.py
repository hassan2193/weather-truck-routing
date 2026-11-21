"""Route ranking and recommendation.

Ordering (from the assessment) is applied as a strict lexicographic comparison:

1. fewest Severe miles
2. fewest High miles
3. lowest average risk
4. shortest travel time

Safety gate: a route containing any *No Travel* segment is never ranked above
a route that has none ("never recommend a route that violates the No Travel
rules when a safe alternative exists"). Among routes that all violate, the one
with the fewest No Travel miles comes first, then the normal order applies.

Segments without weather data are not counted as any risk class. A route with
*no* assessed miles gets an infinite average risk so missing data is never
rewarded.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .metrics import RouteMetrics

# Distances are compared after rounding away floating point noise only.
_PRECISION = 6


def ranking_key(m: RouteMetrics) -> tuple:
    avg = float("inf") if m.average_risk is None else round(m.average_risk, _PRECISION)
    return (
        m.has_no_travel,
        round(m.no_travel_miles, _PRECISION),
        round(m.severe_miles, _PRECISION),
        round(m.high_miles, _PRECISION),
        avg,
        round(m.duration_s, _PRECISION),
    )


@dataclass(frozen=True)
class RankedRoute:
    key: str
    rank: int  # 1 = recommended
    metrics: RouteMetrics


def rank_routes(routes: Mapping[str, RouteMetrics]) -> list[RankedRoute]:
    """Rank routes best-first. Ties keep the input order (stable sort)."""
    ordered = sorted(routes.items(), key=lambda kv: ranking_key(kv[1]))
    return [RankedRoute(key, i + 1, m) for i, (key, m) in enumerate(ordered)]
