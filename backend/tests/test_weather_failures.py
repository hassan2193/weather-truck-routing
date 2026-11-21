"""Regression tests for the production weather failure (every checkpoint "Weather service error").

In production every Open-Meteo call failed while routing worked, and the API only said
"weather service error". The response now carries Open-Meteo's own HTTP status and reason
(never the request URL, which can contain the API key), and weather is still never invented.
"""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses
from django.conf import settings
from django.utils import timezone as djtz
from rest_framework.test import APIClient

from . import helpers

pytestmark = pytest.mark.django_db

# Open-Meteo's real error bodies (status + JSON "reason")
RATE_LIMITED = (429, {"error": True, "reason": "Daily API request limit exceeded. Please try again tomorrow."})
INVALID_KEY = (400, {"error": True, "reason": "The supplied API key is invalid."})


def nyc_to_boston():
    """The failing production request: New York -> Boston, 20,000 lb, 25-mile checkpoints."""
    return {
        "origin": {"label": "New York, NY", "lat": 40.7127281, "lon": -74.0060152},
        "destination": {"label": "Boston, MA", "lat": 42.3554334, "lon": -71.060511},
        "departure_time": (djtz.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:00:00.000Z"),
        "load_weight_lb": 20000,
        "interval_miles": 25,
    }


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body())
        yield mock


def open_meteo_error(rsps, status, body):
    calls = []

    def reply(request):
        calls.append(request.url)
        import json

        return status, {}, json.dumps(body)

    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=reply, content_type="application/json")
    return calls


def analyze():
    r = APIClient().post("/api/routes/analyze/", nyc_to_boston(), format="json")
    assert r.status_code == 201, r.content  # routing still works; weather failure is not fatal
    return r.json()


def assert_no_invented_weather(data):
    for route in data["routes"]:
        assert route["metrics"]["weather_coverage"] == 0
        assert route["metrics"]["average_risk"] is None
        for cp in route["checkpoints"]:
            assert cp["weather"]["status"] == "provider_error"
            assert cp["weather"]["wind_mph"] is None and cp["risk"] is None


def test_rate_limited_weather_reports_the_actual_cause(rsps):
    calls = open_meteo_error(rsps, *RATE_LIMITED)
    data = analyze()
    assert_no_invented_weather(data)
    cause = "Weather service error (HTTP 429): Daily API request limit exceeded. Please try again tomorrow."
    assert cause in data["weather_stats"]["errors"]
    assert any("could not be retrieved" in w and cause in w for w in data["warnings"])
    # bounded retries: at most 3 tries per batch, and the batch count is what the stats report
    assert len(calls) <= 3 * data["weather_stats"]["upstream_requests"]


def test_invalid_api_key_reports_the_actual_cause(rsps, settings):
    settings.OPEN_METEO_API_KEY = "not-a-real-key"
    open_meteo_error(rsps, *INVALID_KEY)
    data = analyze()
    assert_no_invented_weather(data)
    assert data["weather_stats"]["errors"] == ["Weather service error (HTTP 400): The supplied API key is invalid."]


def test_network_error_never_exposes_the_api_key(rsps, settings, caplog):
    settings.OPEN_METEO_API_KEY = "SECRET-KEY-123"
    # requests puts the full URL (with ?apikey=...) into the exception text
    leaky = requests.ConnectionError(
        "HTTPSConnectionPool(host='api.open-meteo.com'): Max retries exceeded with url: "
        "/v1/forecast?latitude=40.7&apikey=SECRET-KEY-123"
    )
    rsps.add(responses.GET, settings.OPEN_METEO_URL, body=leaky)
    with caplog.at_level("DEBUG"):
        r = APIClient().post("/api/routes/analyze/", nyc_to_boston(), format="json")
    assert r.status_code == 201
    assert "SECRET-KEY-123" not in r.content.decode()
    assert "SECRET-KEY-123" not in caplog.text
    assert r.json()["weather_stats"]["errors"] == ["Weather service could not be reached (ConnectionError)"]
    assert_no_invented_weather(r.json())


def test_forecast_endpoint_reports_the_cause_too(rsps):
    open_meteo_error(rsps, *RATE_LIMITED)
    data = analyze()
    f = APIClient().get(f"/api/routes/{data['routes'][0]['id']}/forecast/").json()
    assert f["stats"]["failed_locations"] == f["stats"]["unique_locations"] > 0
    assert f["stats"]["errors"] and "HTTP 429" in f["stats"]["errors"][0]
    assert all(v is None for p in f["heat"] for v in p["risk"])  # nothing invented for the slider either


def test_weather_request_is_built_as_documented(rsps):
    seen = []
    callback = helpers.open_meteo_callback()

    def spy(request):
        seen.append(parse_qs(urlparse(request.url).query))
        return callback(request)

    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=spy, content_type="application/json")
    data = analyze()
    assert data["weather_stats"]["failed_locations"] == 0 and data["weather_stats"].get("errors") == []
    q = seen[0]
    assert q["hourly"] == ["wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"]
    assert q["wind_speed_unit"] == ["mph"] and q["precipitation_unit"] == ["inch"] and q["timezone"] == ["GMT"]
    lats, lons = q["latitude"][0].split(","), q["longitude"][0].split(",")
    assert len(lats) == len(lons) == data["weather_stats"]["unique_locations"]
    # every requested coordinate is (grid-snapped) on one of the returned checkpoints, nothing else
    cps = [(c["lat"], c["lon"]) for r in data["routes"] for c in r["checkpoints"]]
    grid = settings.WEATHER_GRID_DEGREES
    for lat, lon in zip(map(float, lats), map(float, lons)):
        assert any(abs(lat - a) <= grid / 2 + 1e-6 and abs(lon - b) <= grid / 2 + 1e-6 for a, b in cps)
    assert "apikey" not in q
    assert all(r["metrics"]["weather_coverage"] == 1.0 for r in data["routes"])
