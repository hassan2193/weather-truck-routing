"""Find up to three genuinely distinct truck routes.

Step 1 - ask Valhalla directly (best route + up to 2 alternates) and keep only routes
         that are geometrically distinct (near-duplicates are dropped).
Step 2 - if fewer than three remain, re-route iteratively: ask Valhalla again with small
         ``exclude_polygons`` "road blocks" placed along the routes already found, so it
         has to propose a different corridor. Every candidate is a real Valhalla truck
         route; it is accepted only if it is distinct from all accepted routes and not an
         excessive detour.

If three distinct routes cannot be found, the search returns what it has together with
an explanation. Nothing is ever synthesised.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from . import valhalla
from .diversity import MIN_UNIQUE_FRACTION, avoidance_polygons, compare
from .errors import NoRouteFound, RoutingProviderError
from .geometry import LatLon
from .valhalla import ProviderRoute

logger = logging.getLogger(__name__)

TARGET_ROUTES = 3
# A diversified route may take at most this multiple of the fastest route's drive time.
MAX_DETOUR_RATIO = 1.5
# Block positions (fractions of route length) for successive re-routing attempts.
ATTEMPT_PLANS: tuple[tuple[float, ...], ...] = (
    (0.3, 0.5, 0.7),
    (0.2, 0.4, 0.6, 0.8),
    (0.35, 0.55, 0.75),
    (0.25, 0.45, 0.65),
)
ATTEMPT_TIMEOUT_S = 30.0
SEARCH_BUDGET_S = 60.0
MIN_DIVERSIFY_MILES = 5.0


@dataclass
class RouteSearch:
    routes: list[ProviderRoute]
    provider_suggested: int = 0  # routes returned by the first request
    provider_distinct: int = 0  # of those, genuinely distinct
    attempts: int = 0  # re-routing requests made
    rejected_duplicates: int = 0
    rejected_detours: int = 0
    failed_attempts: int = 0  # requests that errored or found no path
    notes: list[str] = field(default_factory=list)

    @property
    def diversified(self) -> int:
        return sum(r.source == "diversified" for r in self.routes)

    def to_dict(self) -> dict:
        return {
            "target": TARGET_ROUTES,
            "found": len(self.routes),
            "provider_suggested": self.provider_suggested,
            "provider_distinct": self.provider_distinct,
            "diversified": self.diversified,
            "attempts": self.attempts,
            "rejected_duplicates": self.rejected_duplicates,
            "rejected_detours": self.rejected_detours,
            "failed_attempts": self.failed_attempts,
        }

    def explanation(self) -> str | None:
        """User-facing explanation when diversification was used or three routes were not found."""
        if len(self.routes) >= TARGET_ROUTES and not self.diversified:
            return None

        def plural(n: int, word: str) -> str:
            return f"{n} {word}{'' if n == 1 else 's'}"

        direct = f"The routing service suggested {plural(self.provider_distinct, 'distinct truck route')}"
        if self.provider_suggested > self.provider_distinct:
            dup = self.provider_suggested - self.provider_distinct
            direct += f" ({dup} more {'was a near-duplicate' if dup == 1 else 'were near-duplicates'})"
        if len(self.routes) >= TARGET_ROUTES:
            return (
                f"{direct}; {self.diversified} more {'was' if self.diversified == 1 else 'were'} found by asking "
                "it to avoid sections of those routes. Every route shown is a real truck route."
            )
        outcomes = []
        if self.rejected_duplicates:
            outcomes.append(
                f"{plural(self.rejected_duplicates, 'candidate route')} overlapped an existing route by more than "
                f"{100 - int(MIN_UNIQUE_FRACTION * 100)}%"
            )
        if self.rejected_detours:
            slow = plural(self.rejected_detours, "candidate route")
            outcomes.append(f"{slow} took over {MAX_DETOUR_RATIO:g}x the fastest drive time")
        if self.failed_attempts:
            outcomes.append(f"{plural(self.failed_attempts, 'attempt')} found no path or failed")
        if self.diversified:
            outcomes.append(f"{plural(self.diversified, 'new route')} accepted")
        tried = ""
        if self.attempts:
            made = plural(self.attempts, "re-routing attempt")
            tried = f" We made {made} around sections of the found routes: {'; '.join(outcomes)}."
        return (
            f"Only {plural(len(self.routes), 'genuinely distinct truck route')} could be found for this trip. "
            f"{direct}.{tried} No routes were invented."
        )


def _accept(candidate: ProviderRoute, search: RouteSearch) -> bool:
    verdict = compare(candidate.geometry, candidate.distance_mi, [r.geometry for r in search.routes])
    if not verdict.distinct:
        search.rejected_duplicates += 1
        return False
    if search.routes and candidate.source == "diversified":
        fastest = min(r.duration_s for r in search.routes)
        if candidate.duration_s > fastest * MAX_DETOUR_RATIO:
            search.rejected_detours += 1
            return False
    search.routes.append(candidate)
    return True


def find_routes(origin: LatLon, destination: LatLon, load_lb: float) -> RouteSearch:
    """Return up to three distinct truck routes (errors from the *first* request propagate)."""
    started = time.monotonic()
    first = valhalla.request_routes(origin, destination, load_lb, alternates=TARGET_ROUTES - 1)
    search = RouteSearch(routes=[], provider_suggested=len(first))
    for route in first:
        if len(search.routes) < TARGET_ROUTES:
            _accept(route, search)
    search.provider_distinct = len(search.routes)
    # near-duplicates among the provider's own suggestions are not counted as rejected attempts
    search.rejected_duplicates = 0

    if len(search.routes) >= TARGET_ROUTES:
        return search
    if search.routes[0].distance_mi < MIN_DIVERSIFY_MILES:
        search.notes.append("Trip too short for alternative corridors.")
        return search

    for fractions in ATTEMPT_PLANS:
        if len(search.routes) >= TARGET_ROUTES:
            break
        if time.monotonic() - started > SEARCH_BUDGET_S:
            logger.info("Route diversification stopped: time budget exhausted")
            break
        polygons = avoidance_polygons([r.geometry for r in search.routes], fractions, origin, destination)
        if not polygons:
            break
        search.attempts += 1
        try:
            candidates = valhalla.request_routes(
                origin,
                destination,
                load_lb,
                alternates=TARGET_ROUTES - 1,
                exclude_polygons=polygons,
                timeout=ATTEMPT_TIMEOUT_S,
            )
        except (NoRouteFound, RoutingProviderError) as exc:
            logger.info("Diversification attempt %d failed: %s", search.attempts, exc)
            search.failed_attempts += 1
            continue
        for candidate in candidates:
            if len(search.routes) >= TARGET_ROUTES:
                break
            candidate.source = "diversified"
            _accept(candidate, search)

    logger.info("Route search: %s", search.to_dict())
    return search
