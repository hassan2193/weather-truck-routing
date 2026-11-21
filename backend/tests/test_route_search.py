"""Three-route search: direct alternates, distinctness checks and diversified re-routing."""
import json
from datetime import timedelta

import pytest
import requests
import responses
from django.conf import settings
from django.utils import timezone as djtz
from rest_framework.test import APIClient

from routing import route_search
from routing.diversity import (
    POLYGON_BUDGET_KM,
    avoidance_polygons,
    compare,
    ring_circumference_km,
    unique_fraction,
)
from routing.geometry import cumulative_miles, haversine_miles

from . import helpers

# ---------------------------------------------------------------------------
# geometry: duplicate / distinct detection (pure)
# ---------------------------------------------------------------------------
BASE = helpers.route_points(0.0, n=200)
BASE_MI = cumulative_miles(BASE)[-1]


def jitter(points, amount=0.001):
    return [(lat + (amount if i % 2 else -amount), lon + amount) for i, (lat, lon) in enumerate(points)]


def local_detour(points, start=0.47, end=0.50, shift=0.05):
    n = len(points)
    return [(lat, lon + shift) if start * n <= i <= end * n else (lat, lon) for i, (lat, lon) in enumerate(points)]


def test_identical_route_is_a_duplicate():
    assert unique_fraction(BASE, BASE) == 0
    assert not compare(BASE, BASE_MI, [BASE]).distinct


def test_minor_coordinate_differences_are_duplicates():
    # ~0.07 mi of noise on every vertex (carriageway / polyline noise)
    assert unique_fraction(jitter(BASE), BASE) == 0
    assert not compare(jitter(BASE), BASE_MI, [BASE]).distinct


def test_parallel_road_within_tolerance_is_the_same_corridor():
    parallel = [(lat, lon + 0.004) for lat, lon in BASE]  # ~0.2 mi east the whole way
    assert not compare(parallel, BASE_MI, [BASE]).distinct


def test_short_local_detour_is_not_a_distinct_route():
    v = compare(local_detour(BASE), BASE_MI, [BASE])
    assert 0 < v.unique_fraction < 0.15 and not v.distinct


def test_different_corridor_is_distinct():
    other = helpers.route_points(1.0, n=200)
    v = compare(other, cumulative_miles(other)[-1], [BASE])
    assert v.distinct and v.unique_fraction > 0.5


def test_candidate_must_differ_from_every_accepted_route():
    east = helpers.route_points(1.0, n=200)
    assert compare(east, 200, [BASE]).distinct
    assert not compare(jitter(east), 200, [BASE, east]).distinct


def test_tiny_unique_mileage_is_rejected_even_if_fraction_is_high():
    v = compare(helpers.route_points(1.0, n=50), 1.5, [BASE])  # pretend the route is only 1.5 mi long
    assert not v.distinct


# ---------------------------------------------------------------------------
# avoidance polygons (pure)
# ---------------------------------------------------------------------------
def test_polygons_stay_within_provider_circumference_limit():
    for routes, fractions in (([BASE], (0.3, 0.5, 0.7)), ([BASE, BASE, BASE], (0.2, 0.4, 0.6, 0.8))):
        polys = avoidance_polygons(routes, fractions, helpers.ORIGIN, helpers.DEST)
        assert polys
        assert sum(ring_circumference_km(p) for p in polys) <= POLYGON_BUDGET_KM < 10.0


def test_polygons_are_centred_on_the_route_and_closed():
    polys = avoidance_polygons([BASE], (0.3, 0.5, 0.7), helpers.ORIGIN, helpers.DEST)
    assert len(polys) == 3
    for ring in polys:
        assert ring[0] == ring[-1]
        clat = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
        clon = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        assert min(haversine_miles((clat, clon), p) for p in BASE) < 0.5


def test_no_polygons_near_origin_or_destination():
    short = helpers.route_points(0.0, n=100)[:2]  # ~1.7-mile stub: every point is within 3 mi of an end
    assert avoidance_polygons([short], (0.3, 0.5, 0.7), helpers.ORIGIN, short[-1]) == []


# ---------------------------------------------------------------------------
# full pipeline through the API with a scripted Valhalla
# ---------------------------------------------------------------------------
pytestmark_db = pytest.mark.django_db


def body(*bulges):
    trips = [helpers.valhalla_trip(helpers.route_points(b)) for b in bulges]
    out = {"trip": trips[0]}
    if len(trips) > 1:
        out["alternates"] = [{"trip": t} for t in trips[1:]]
    return out


def jittered_body(bulge):
    trip = helpers.valhalla_trip(jitter(helpers.route_points(bulge)))
    return trip


class ScriptedValhalla:
    """Replies to successive /route calls from a script; records every request body."""

    def __init__(self, rsps, script):
        self.script = list(script)
        self.requests = []
        rsps.add_callback(responses.POST, f"{settings.VALHALLA_URL}/route", callback=self, content_type="application/json")

    def __call__(self, request):
        self.requests.append(json.loads(request.body))
        item = self.script.pop(0) if self.script else {"error_code": 442, "error": "No path could be found"}
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            status, payload = item
            return status, {}, json.dumps(payload)
        if isinstance(item, dict) and "error_code" in item:
            return 400, {}, json.dumps(item)
        return 200, {}, json.dumps(item)

    @property
    def diversification_requests(self):
        return [r for r in self.requests if "exclude_polygons" in r]


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def run(rsps, script, weather=helpers.calm, load=25_000):
    valhalla = ScriptedValhalla(rsps, script)
    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=helpers.open_meteo_callback(weather),
                      content_type="application/json")
    r = APIClient().post("/api/routes/analyze/", {
        "origin": {"label": "Chicago", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]},
        "destination": {"label": "Indianapolis", "lat": helpers.DEST[0], "lon": helpers.DEST[1]},
        "departure_time": (djtz.now() + timedelta(hours=2)).isoformat(),
        "load_weight_lb": load,
        "interval_miles": 10,
    }, format="json")
    assert r.status_code == 201, r.content
    return r.json(), valhalla


def assert_fully_analysed(data):
    """Every route (direct or diversified) got its own checkpoints, ETAs, weather and risk."""
    for route in data["routes"]:
        cps = route["checkpoints"]
        assert cps and cps[-1]["distance_mi"] == pytest.approx(route["distance_mi"])
        assert all(a["eta"] < b["eta"] for a, b in zip(cps, cps[1:]))
        assert all(c["weather"]["status"] == "ok" and c["risk"] is not None for c in cps)
        assert route["metrics"]["weather_coverage"] == 1.0
    assert sum(r["is_recommended"] for r in data["routes"]) == 1
    assert sorted(r["rank"] for r in data["routes"]) == list(range(1, len(data["routes"]) + 1))


@pytest.mark.django_db
def test_three_routes_returned_directly_needs_no_extra_requests(rsps):
    data, valhalla = run(rsps, [body(0.0, 1.0, -1.0)])
    assert len(valhalla.requests) == 1 and not valhalla.diversification_requests
    assert len(data["routes"]) == 3 and {r["source"] for r in data["routes"]} == {"provider"}
    assert data["route_search"]["provider_distinct"] == 3 and data["route_search"]["attempts"] == 0
    assert data["route_search"]["message"] is None
    assert_fully_analysed(data)


@pytest.mark.django_db
def test_two_routes_initially_are_completed_by_diversification(rsps):
    data, valhalla = run(rsps, [body(0.0, 1.0), body(-1.0)])
    assert len(data["routes"]) == 3
    assert sorted(r["source"] for r in data["routes"]) == ["diversified", "provider", "provider"]
    assert len(valhalla.diversification_requests) == 1
    polys = valhalla.diversification_requests[0]["exclude_polygons"]
    assert sum(ring_circumference_km(p) for p in polys) < 10.0
    assert valhalla.diversification_requests[0]["costing"] == "truck"  # still truck routing
    assert "found by asking it to avoid sections" in data["route_search"]["message"]
    assert_fully_analysed(data)


@pytest.mark.django_db
def test_one_route_initially_is_completed_by_diversification(rsps):
    data, valhalla = run(rsps, [body(0.0), body(1.0), body(-1.0)])
    assert len(data["routes"]) == 3
    assert data["route_search"]["provider_distinct"] == 1 and data["route_search"]["diversified"] == 2
    assert len(valhalla.diversification_requests) == 2
    # the second attempt also avoids the route found by the first one
    assert len(valhalla.diversification_requests[1]["exclude_polygons"]) > len(valhalla.diversification_requests[0]["exclude_polygons"])
    assert_fully_analysed(data)


@pytest.mark.django_db
def test_alternates_inside_a_diversified_response_are_used(rsps):
    data, valhalla = run(rsps, [body(0.0), body(0.0, 1.0, -1.0)])  # reply repeats the primary + 2 new
    assert len(data["routes"]) == 3 and len(valhalla.requests) == 2
    assert data["route_search"]["rejected_duplicates"] == 1  # the repeated primary


@pytest.mark.django_db
def test_near_duplicate_provider_alternates_are_dropped(rsps):
    dup = body(0.0, 1.0)
    dup["alternates"].append({"trip": jittered_body(1.0)})  # same corridor as the 2nd route, tiny offsets
    data, valhalla = run(rsps, [dup, body(-1.0)])
    assert data["route_search"]["provider_suggested"] == 3 and data["route_search"]["provider_distinct"] == 2
    assert len(data["routes"]) == 3 and data["route_search"]["diversified"] == 1


@pytest.mark.django_db
def test_no_valid_alternatives_gives_a_clear_explanation(rsps):
    # every re-routing attempt comes back with the same road
    data, valhalla = run(rsps, [body(0.0)] + [body(0.0)] * len(route_search.ATTEMPT_PLANS))
    assert len(data["routes"]) == 1
    assert data["route_search"]["attempts"] == len(route_search.ATTEMPT_PLANS)
    msg = data["route_search"]["message"]
    assert msg.startswith("Only 1 genuinely distinct truck route could be found")
    assert "overlapped an existing route" in msg and "No routes were invented" in msg
    assert msg in data["warnings"]
    assert_fully_analysed(data)


@pytest.mark.django_db
def test_no_path_when_avoiding_sections_is_reported(rsps):
    no_path = {"error_code": 442, "error": "No path could be found for input"}
    data, _ = run(rsps, [body(0.0, 1.0)] + [no_path] * len(route_search.ATTEMPT_PLANS))
    assert len(data["routes"]) == 2
    assert data["route_search"]["failed_attempts"] == len(route_search.ATTEMPT_PLANS)
    assert "found no path or failed" in data["route_search"]["message"]


@pytest.mark.django_db
def test_excessive_detours_are_rejected(rsps):
    data, _ = run(rsps, [body(0.0, 1.0)] + [body(9.0)] * len(route_search.ATTEMPT_PLANS))
    assert len(data["routes"]) == 2
    assert data["route_search"]["rejected_detours"] == len(route_search.ATTEMPT_PLANS)
    assert "1.5x the fastest drive time" in data["route_search"]["message"]


@pytest.mark.django_db
def test_provider_failure_during_diversification_keeps_the_found_routes(rsps):
    # HTTP 500 is not retried by the shared session (502/503/504/429 are), so it models a hard failure
    script = [body(0.0, 1.0), (500, {"error": "boom"}), requests.ConnectionError("reset"), body(-1.0)]
    data, valhalla = run(rsps, script)
    assert len(data["routes"]) == 3
    assert data["route_search"]["failed_attempts"] == 2 and data["route_search"]["attempts"] == 3
    assert_fully_analysed(data)


@pytest.mark.django_db
def test_provider_failure_on_the_first_request_is_an_error(rsps):
    ScriptedValhalla(rsps, [(500, {"error": "down"})])
    r = APIClient().post("/api/routes/analyze/", {
        "origin": {"label": "A", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]},
        "destination": {"label": "B", "lat": helpers.DEST[0], "lon": helpers.DEST[1]},
        "departure_time": (djtz.now() + timedelta(hours=2)).isoformat(),
        "load_weight_lb": 1000, "interval_miles": 25,
    }, format="json")
    assert r.status_code == 502 and r.json()["error"]["code"] == "routing_unavailable"


@pytest.mark.django_db
def test_search_stops_when_time_budget_is_spent(rsps, monkeypatch):
    monkeypatch.setattr(route_search, "SEARCH_BUDGET_S", -1)
    data, valhalla = run(rsps, [body(0.0), body(1.0)])
    assert len(valhalla.requests) == 1 and len(data["routes"]) == 1


# ---------------------------------------------------------------------------
# safety rules apply to diversified routes like any other
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_diversified_route_is_compared_and_can_win_when_direct_route_is_unsafe(rsps):
    # 48 mph wind sits on the straight route (bulge 0); with 45,000 lb that is No Travel.
    data, _ = run(rsps, [body(0.0), body(1.0), body(-1.0)], weather=helpers.severe_on_route_a, load=45_000)
    by_source = {r["source"]: r for r in data["routes"]}
    direct = next(r for r in data["routes"] if r["source"] == "provider")
    assert direct["no_travel"] and not direct["is_recommended"]
    winner = next(r for r in data["routes"] if r["is_recommended"])
    assert winner["source"] == "diversified" and not winner["no_travel"]
    assert "diversified" in by_source


@pytest.mark.django_db
def test_unsafe_diversified_route_is_never_recommended_over_safe_direct_route(rsps):
    def wind_on_east_route(lat, lon, i):
        return {**helpers.calm(lat, lon, i), "wind_speed_10m": 60.0 if lon > -86.3 and 40.3 < lat < 41.3 else 8.0}

    data, _ = run(rsps, [body(0.0), body(1.0), body(-1.0)], weather=wind_on_east_route, load=10_000)
    east = next(r for r in data["routes"] if r["source"] == "diversified" and r["no_travel"])
    assert not east["is_recommended"]
    assert not next(r for r in data["routes"] if r["is_recommended"])["no_travel"]
