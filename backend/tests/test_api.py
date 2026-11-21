"""End-to-end API tests: real pipeline + database, with the provider HTTP layer mocked."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import requests
import responses
from django.conf import settings
from django.utils import timezone as djtz
from rest_framework.test import APIClient

from . import helpers

pytestmark = pytest.mark.django_db
URL = "/api/routes/analyze/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def payload(**overrides):
    body = {
        "origin": {"label": "Chicago, IL", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]},
        "destination": {"label": "Indianapolis, IN", "lat": helpers.DEST[0], "lon": helpers.DEST[1]},
        "departure_time": (djtz.now() + timedelta(hours=2)).isoformat(),
        "load_weight_lb": 25_000,
        "interval_miles": 10,
    }
    body.update(overrides)
    return body


def analyze(client, **overrides):
    return client.post(URL, payload(**overrides), format="json")


# --- happy path -----------------------------------------------------------------------
def test_analyze_returns_three_routes_with_checkpoints_and_recommendation(client, rsps):
    helpers.install(rsps)
    r = analyze(client)
    assert r.status_code == 201, r.content
    data = r.json()
    assert [x["label"] for x in data["routes"]] == ["A", "B", "C"]
    durations = [x["duration_s"] for x in data["routes"]]
    assert durations == sorted(durations)  # A is the fastest
    assert sum(x["is_recommended"] for x in data["routes"]) == 1
    assert data["recommendation"]["headline"] and data["recommendation"]["route_id"]
    for route in data["routes"]:
        cps = route["checkpoints"]
        assert cps[0]["distance_mi"] == 0 and cps[-1]["distance_mi"] == pytest.approx(route["distance_mi"])
        assert all(a["eta"] < b["eta"] for a, b in zip(cps, cps[1:]))
        assert all(c["weather"]["status"] == "ok" and c["risk"]["label"] == "Low" for c in cps)
        assert sum(c["segment_mi"] for c in cps) == pytest.approx(route["distance_mi"])
        assert route["geometry"] and route["summary"].startswith("via")


def test_checkpoint_interval_controls_checkpoint_count(client, rsps):
    helpers.install(rsps)
    counts = {}
    for interval in (10, 25, 50):
        cache_buster = {"departure_time": (djtz.now() + timedelta(hours=2, minutes=interval)).isoformat()}
        counts[interval] = len(analyze(client, interval_miles=interval, **cache_buster).json()["routes"][0]["checkpoints"])
    assert counts[10] > counts[25] > counts[50] >= 2


def test_weather_requests_are_deduplicated_and_batched(client, rsps):
    calls = helpers.install(rsps)
    data = analyze(client).json()
    total_checkpoints = sum(len(r["checkpoints"]) for r in data["routes"])
    stats = data["weather_stats"]
    assert stats["checkpoints"] == total_checkpoints
    assert stats["unique_locations"] < total_checkpoints  # shared road segments / nearby points collapse
    assert sum(calls.calls) == stats["unique_locations"]  # each unique cell is fetched exactly once
    assert max(calls.calls) <= settings.WEATHER_BATCH_SIZE and len(calls.calls) == stats["upstream_requests"]


def test_second_identical_analysis_hits_the_weather_cache(client, rsps):
    calls = helpers.install(rsps)
    analyze(client)
    first = len(calls.calls)
    second = analyze(client).json()
    assert len(calls.calls) == first
    assert second["weather_stats"]["upstream_requests"] == 0 and second["weather_stats"]["cache_hits"] > 0


# --- recommendation behaviour through the API -------------------------------------------------
def test_recommends_route_avoiding_severe_weather(client, rsps):
    helpers.install(rsps, weather=helpers.severe_on_route_a)
    data = analyze(client, load_weight_lb=25_000).json()
    by_label = {r["label"]: r for r in data["routes"]}
    assert by_label["A"]["metrics"]["severe_miles"] > 0
    assert by_label["B"]["metrics"]["severe_miles"] == 0
    assert not by_label["A"]["is_recommended"]
    assert data["recommendation"]["route_label"] in {"B", "C"}
    assert "severe-weather miles" in data["recommendation"]["headline"]


def test_heavy_load_turns_same_wind_into_no_travel_and_flags_route(client, rsps):
    helpers.install(rsps, weather=helpers.severe_on_route_a)
    data = analyze(client, load_weight_lb=45_000).json()  # 48 mph with >30,000 lb => No Travel
    a = next(r for r in data["routes"] if r["label"] == "A")
    assert a["no_travel"] and a["metrics"]["no_travel_miles"] > 0
    assert a["no_travel_reasons"] and "No Travel" in a["no_travel_reasons"][0]
    assert any(c["risk"]["label"] == "No Travel" and c["risk"]["load_rule"] for c in a["checkpoints"])
    assert not a["is_recommended"]
    assert not data["recommendation"]["all_routes_unsafe"]


def test_all_routes_unsafe_is_reported(client, rsps):
    helpers.install(rsps, weather=helpers.severe_everywhere)
    data = analyze(client, load_weight_lb=45_000).json()
    assert data["recommendation"]["all_routes_unsafe"] is True
    assert all(r["no_travel"] for r in data["routes"])
    assert any("No Travel" in w for w in data["recommendation"]["warnings"])


# --- graceful degradation -------------------------------------------------------------------
def test_fewer_than_three_routes_is_reported_not_faked(client, rsps):
    helpers.install(rsps, valhalla=helpers.valhalla_body(bulges=(0.0,)))
    data = analyze(client).json()
    assert len(data["routes"]) == 1
    assert any("Only 1 genuinely distinct truck route" in w and "No routes were invented" in w for w in data["warnings"])


def test_identical_alternates_are_collapsed(client, rsps):
    helpers.install(rsps, valhalla=helpers.valhalla_body(bulges=(0.0, 0.0, 0.0)))
    assert len(analyze(client).json()["routes"]) == 1


def test_weather_outage_yields_unavailable_checkpoints_not_fake_low(client, rsps):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body())
    rsps.add(responses.GET, settings.OPEN_METEO_URL, status=500, json={"error": True, "reason": "down"})
    r = analyze(client)
    assert r.status_code == 201
    data = r.json()
    assert any("could not be retrieved" in w for w in data["warnings"])
    for route in data["routes"]:
        assert all(c["weather"]["status"] == "provider_error" and c["risk"] is None for c in route["checkpoints"])
        assert route["metrics"]["unknown_miles"] == pytest.approx(route["distance_mi"], abs=0.01)
        assert route["metrics"]["average_risk"] is None
    assert "no weather data" in data["recommendation"]["headline"]


def test_checkpoints_past_the_forecast_horizon_are_marked_unavailable(client, rsps):
    helpers.install(rsps)
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    departure = midnight + timedelta(days=15, hours=22)  # forecast ends 15d 23:00 from today's midnight
    r = analyze(client, departure_time=departure.isoformat())
    assert r.status_code == 201, r.content
    data = r.json()
    cps = data["routes"][0]["checkpoints"]
    assert cps[0]["weather"]["status"] == "ok"
    assert cps[-1]["weather"]["status"] == "beyond_forecast_horizon" and cps[-1]["risk"] is None
    assert any("forecast horizon" in w for w in data["warnings"])


# --- errors ---------------------------------------------------------------------------------
def test_no_route_found_returns_422(client, rsps):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", status=400,
             json={"error_code": 442, "error": "No path could be found for input"})
    r = analyze(client)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_route"


def test_routing_service_down_returns_502(client, rsps):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", status=503, body="unavailable")
    r = analyze(client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "routing_unavailable"


def test_routing_network_failure_returns_502(client, rsps):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", body=requests.ConnectionError("dns"))
    r = analyze(client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "routing_unavailable"


def test_origin_equals_destination_is_rejected(client, rsps):
    helpers.install(rsps)
    r = analyze(client, destination={"label": "Same", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]})
    assert r.status_code == 422 and "too close" in r.json()["error"]["message"]


def test_free_text_places_are_geocoded_server_side(client, rsps):
    helpers.install(rsps)
    rsps.add(responses.GET, settings.PHOTON_URL, json={"features": [
        {"geometry": {"coordinates": [helpers.ORIGIN[1], helpers.ORIGIN[0]]}, "properties": {"name": "Chicago", "state": "Illinois", "country": "United States"}}]})
    r = analyze(client, origin="Chicago")
    assert r.status_code == 201
    assert r.json()["origin"]["label"] == "Chicago, Illinois, United States"


def test_unknown_address_returns_422(client, rsps):
    rsps.add(responses.GET, settings.PHOTON_URL, json={"features": []})
    rsps.add(responses.GET, settings.NOMINATIM_URL, json=[])
    r = analyze(client, origin="zzzzzzzzzz nowhere")
    assert r.status_code == 422 and r.json()["error"]["code"] == "address_not_found"


@pytest.mark.parametrize("override,field", [
    ({"load_weight_lb": -1}, "load_weight_lb"),
    ({"load_weight_lb": 999_999}, "load_weight_lb"),
    ({"load_weight_lb": "heavy"}, "load_weight_lb"),
    ({"interval_miles": 15}, "interval_miles"),
    ({"departure_time": "not-a-date"}, "departure_time"),
    ({"departure_time": (djtz.now() - timedelta(days=2)).isoformat()}, "departure_time"),
    ({"departure_time": (djtz.now() + timedelta(days=40)).isoformat()}, "departure_time"),
    ({"origin": ""}, "origin"),
    ({"destination": {"lat": 95, "lon": 0}}, "destination"),
])
def test_input_validation(client, rsps, override, field):
    r = analyze(client, **override)
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error" and field in err["details"]
    assert len(rsps.calls) == 0  # nothing was sent to any provider


def test_missing_fields_are_all_reported(client):
    r = client.post(URL, {}, format="json")
    assert r.status_code == 400
    assert {"origin", "destination", "departure_time", "load_weight_lb"} <= set(r.json()["error"]["details"])


# --- read endpoints ---------------------------------------------------------------------------
@pytest.fixture
def analysis(client, rsps):
    helpers.install(rsps, weather=helpers.severe_on_route_a)
    return analyze(client).json()


def test_route_detail_and_checkpoints_endpoints(client, analysis):
    route = analysis["routes"][0]
    detail = client.get(f"/api/routes/{route['id']}/")
    assert detail.status_code == 200 and detail.json()["label"] == "A" and "checkpoints" not in detail.json()
    cps = client.get(f"/api/routes/{route['id']}/checkpoints/").json()
    assert cps["count"] == len(route["checkpoints"]) and cps["checkpoints"][0]["sequence"] == 0
    assert client.get(f"/api/analyses/{analysis['id']}/").json()["id"] == analysis["id"]


def test_unknown_api_path_returns_json_404(client):
    r = client.get("/api/does-not-exist/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_unknown_ids_return_404(client):
    for path in (f"/api/routes/{uuid.uuid4()}/", f"/api/routes/{uuid.uuid4()}/checkpoints/", f"/api/routes/{uuid.uuid4()}/forecast/"):
        r = client.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_forecast_endpoint_returns_48_hours_of_real_series(client, analysis):
    route = analysis["routes"][0]
    f = client.get(f"/api/routes/{route['id']}/forecast/").json()
    assert len(f["hours"]) == 49 and f["hours"][1] > f["hours"][0]
    assert len(f["checkpoints"]) == len(route["checkpoints"])
    assert f["heat"] and all(len(p["risk"]) == 49 == len(p["wind"]) for p in f["heat"])
    # severe wind on route A must show up in the forecast risk series (Severe = 3 for a 25,000 lb load)
    assert max(max(r for r in p["risk"] if r is not None) for p in f["heat"]) == 3
    # the slider data and the ETA-based checkpoint risk agree on the same weather
    assert max(c["risk"]["level"] for c in route["checkpoints"] if c["risk"]) == 3
    assert max(p["eta_risk"] for p in f["heat"]) == 3
    # heat points are ordered along the route
    d = [p["distance_mi"] for p in f["heat"]]
    assert d == sorted(d)


def test_health_and_geocode_endpoints(client, rsps):
    h = client.get("/api/health/")
    assert h.status_code == 200 and h.json()["database"]["status"] == "ok"
    rsps.add(responses.GET, settings.PHOTON_URL, json={"features": [
        {"geometry": {"coordinates": [-96.79, 32.77]}, "properties": {"name": "Dallas", "state": "Texas", "country": "United States"}}]})
    g = client.get("/api/geocode/", {"q": "Dallas"})
    assert g.status_code == 200 and g.json()["results"][0]["label"] == "Dallas, Texas, United States"
    assert client.get("/api/geocode/", {"q": "a"}).json()["results"] == []
