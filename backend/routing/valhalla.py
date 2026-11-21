"""Valhalla routing client (truck costing, up to 3 alternative routes).

Valhalla returns the best route in ``trip`` plus up to ``alternates`` more in
``alternates``. We use ``costing=truck`` so routes respect truck restrictions,
and read per-maneuver distance/time to build an ETA profile.
"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field

import requests
from django.conf import settings

from config.http import get_session

from .checkpoints import TimeProfile
from .errors import NoRouteFound, RoutingProviderError
from .geometry import LatLon, decode_polyline

logger = logging.getLogger(__name__)

LB_TO_METRIC_TONS = 0.00045359237
MAX_ROUTES = 3


@dataclass
class ProviderRoute:
    geometry: list[LatLon]
    distance_mi: float
    duration_s: float
    summary: str
    has_toll: bool = False
    has_ferry: bool = False
    time_profile: TimeProfile = field(default=None)  # type: ignore[assignment]
    # "provider": suggested directly by Valhalla; "diversified": found by re-routing around
    # sections of other routes (still a real Valhalla truck route, never synthesised).
    source: str = "provider"


_ROUTE_REF = re.compile(r"([A-Z]{1,3})\s+(\d+[A-Za-z]?)(?:\s+(?:North|South|East|West))?")


def _clean_road_name(name: str) -> str:
    """'I 94 East' -> 'I-94', 'IL 394' -> 'IL-394'; other names are returned unchanged."""
    m = _ROUTE_REF.fullmatch(name.strip())
    return f"{m.group(1)}-{m.group(2)}" if m else name.strip()


def summarize_maneuvers(maneuvers: list[dict], max_roads: int = 3) -> str:
    """'via I-90, I-65' built from the roads covering the most distance."""
    miles: OrderedDict[str, float] = OrderedDict()
    for m in maneuvers:
        names = m.get("street_names") or []
        if not names:
            continue
        # Prefer a numbered route ref ("I 90") over a local name when both exist.
        ref = next((n for n in names if _ROUTE_REF.fullmatch(n.strip())), names[0])
        road = _clean_road_name(ref)
        miles[road] = miles.get(road, 0.0) + float(m.get("length", 0.0))
    if not miles:
        return "Local roads"
    top = sorted(miles, key=lambda r: -miles[r])[:max_roads]
    ordered = [r for r in miles if r in top]  # keep travel order
    return "via " + ", ".join(ordered)


def parse_trip(trip: dict) -> ProviderRoute:
    """Convert one Valhalla ``trip`` object into a :class:`ProviderRoute`."""
    summary = trip["summary"]
    total_mi, total_s = float(summary["length"]), float(summary["time"])
    geometry: list[LatLon] = []
    maneuvers: list[dict] = []
    for leg in trip["legs"]:
        points = decode_polyline(leg["shape"], precision=6)
        geometry.extend(points if not geometry else points[1:])
        maneuvers.extend(leg.get("maneuvers", []))
    if len(geometry) < 2 or total_mi <= 0:
        raise RoutingProviderError("Routing provider returned an empty route")
    segments = [(float(m.get("length", 0)), float(m.get("time", 0))) for m in maneuvers]
    return ProviderRoute(
        geometry=geometry,
        distance_mi=total_mi,
        duration_s=total_s,
        summary=summarize_maneuvers(maneuvers),
        has_toll=bool(summary.get("has_toll")),
        has_ferry=bool(summary.get("has_ferry")),
        time_profile=TimeProfile.from_segments(segments, total_mi, total_s),
    )


def request_routes(
    origin: LatLon,
    destination: LatLon,
    load_lb: float,
    *,
    alternates: int = MAX_ROUTES - 1,
    exclude_polygons: list[list[list[float]]] | None = None,
    timeout: float | None = None,
) -> list[ProviderRoute]:
    """One Valhalla truck routing request: the best route plus up to ``alternates`` more.

    ``exclude_polygons`` (rings of ``[lon, lat]``) makes Valhalla avoid every road that
    intersects them; the diversification step uses it to ask for genuinely different
    routes. Returned routes are exactly what the provider produced, in its order; no
    de-duplication happens here.
    """
    tons = round((load_lb + settings.TRUCK_TARE_LB) * LB_TO_METRIC_TONS, 2)
    body = {
        "locations": [
            {"lat": origin[0], "lon": origin[1], "type": "break"},
            {"lat": destination[0], "lon": destination[1], "type": "break"},
        ],
        "costing": "truck",
        "costing_options": {"truck": {"weight": tons}},
        "alternates": alternates,
        "units": "miles",
        "directions_options": {"units": "miles"},
    }
    if exclude_polygons:
        body["exclude_polygons"] = exclude_polygons
    params = {"api_key": settings.VALHALLA_API_KEY} if settings.VALHALLA_API_KEY else None
    try:
        resp = get_session().post(
            f"{settings.VALHALLA_URL}/route",
            json=body,
            params=params,
            timeout=timeout or settings.ROUTING_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Valhalla request failed: %s", exc)
        raise RoutingProviderError("The routing service could not be reached. Please try again.") from exc

    if resp.status_code == 400 or (resp.status_code == 200 and "trip" not in resp.json()):
        detail = _error_text(resp)
        # 442/443/171 etc: no path / no suitable edges near a location.
        raise NoRouteFound(f"No truck route could be found between these locations ({detail}).")
    if resp.status_code != 200:
        logger.warning("Valhalla returned HTTP %s: %s", resp.status_code, resp.text[:300])
        raise RoutingProviderError(f"The routing service returned an error (HTTP {resp.status_code}).")

    data = resp.json()
    trips = [data["trip"]] + [a["trip"] for a in data.get("alternates", [])]
    return [parse_trip(t) for t in trips]


def _error_text(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("error", resp.text[:120]))
    except ValueError:
        return resp.text[:120]
