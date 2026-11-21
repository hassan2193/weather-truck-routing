"""weather.gov (US National Weather Service) fallback when Open-Meteo fails.

The weather.gov mock reproduces the real API shapes captured from api.weather.gov:
/points -> {properties: {gridId, gridX, gridY}} (404 outside coverage) and
/gridpoints -> {properties: {validTimes, windSpeed[km/h], windGust, quantitativePrecipitation[mm],
snowfallAmount[mm]}} with run-length "start/duration" intervals.
"""
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
import responses
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone as djtz
from rest_framework.test import APIClient

from risk_engine.levels import RiskLevel
from risk_engine.rules import assess
from weather import nws, service
from weather.series import NO_DATA, OK, sample_series

from . import helpers

POINTS_RE = re.compile(r"https://api\.weather\.gov/points/.*")
GRID_RE = re.compile(r"https://api\.weather\.gov/gridpoints/.*")
KMH_PER_MPH = 1.609344


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def grid_props(wind_kmh=16.0, gust_kmh=25.0, qpf_mm_6h=0.0, snow_mm_6h=0.0, start=None, days=7, nulls=False):
    """A gridpoint ``properties`` block in weather.gov's format."""
    start = start or datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    span = timedelta(days=days)
    six = [start + timedelta(hours=6 * i) for i in range(int(span.total_seconds() // 21600))]
    value = (lambda v: None) if nulls else (lambda v: v)
    return {
        "validTimes": f"{iso(start)}/P{days}D",
        "windSpeed": {"uom": "wmoUnit:km_h-1", "values": [{"validTime": f"{iso(start)}/P{days}D", "value": value(wind_kmh)}]},
        "windGust": {"uom": "wmoUnit:km_h-1", "values": [{"validTime": f"{iso(start)}/P{days}D", "value": value(gust_kmh)}]},
        "quantitativePrecipitation": {"uom": "wmoUnit:mm", "values": [{"validTime": f"{iso(t)}/PT6H", "value": value(qpf_mm_6h)} for t in six]},
        "snowfallAmount": {"uom": "wmoUnit:mm", "values": [{"validTime": f"{iso(t)}/PT6H", "value": value(snow_mm_6h)} for t in six]},
    }


class FakeNws:
    """weather.gov stand-in; records every request (url + headers)."""

    def __init__(self, rsps, grid_status=200, not_covered=lambda lat, lon: False, **grid_kwargs):
        self.calls = []
        self.grid_status = grid_status
        self.not_covered = not_covered
        self.grid_kwargs = grid_kwargs
        rsps.add_callback(responses.GET, POINTS_RE, callback=self.points, content_type="application/geo+json")
        rsps.add_callback(responses.GET, GRID_RE, callback=self.grid, content_type="application/geo+json")

    def points(self, request):
        self.calls.append(request)
        lat, lon = map(float, urlparse(request.url).path.rsplit("/", 1)[1].split(","))
        if self.not_covered(lat, lon):
            return 404, {}, json.dumps({"title": "Data Unavailable For Requested Point", "status": 404})
        # ~0.05 deg grid cells so distinct checkpoints map to distinct grids, nearby ones share
        props = {"gridId": "LOT", "gridX": int(round((lon + 180) * 20)), "gridY": int(round((lat + 90) * 20))}
        return 200, {}, json.dumps({"properties": props})

    def grid(self, request):
        self.calls.append(request)
        if self.grid_status != 200:
            return self.grid_status, {}, json.dumps({"title": "Unexpected Problem", "status": self.grid_status})
        return 200, {}, json.dumps({"properties": grid_props(**self.grid_kwargs)})

    def count(self, kind):
        return sum(1 for r in self.calls if f"/{kind}/" in r.url)


@pytest.fixture
def fallback_on(settings):
    settings.WEATHER_FALLBACK_NWS = True
    settings.NWS_URL = "https://api.weather.gov"
    settings.NWS_USER_AGENT = "haulwise-test/1.0 (contact: ops@example.com)"


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def open_meteo_429(rsps):
    calls = []

    def reply(request):
        calls.append(request)
        return 429, {}, json.dumps({"error": True, "reason": "Daily API request limit exceeded. Please try again tomorrow."})

    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=reply, content_type="application/json")
    return calls


# ---------------------------------------------------------------------------
# parsing / conversion (pure)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,hours", [("PT1H", 1), ("PT6H", 6), ("P1DT6H", 30), ("P7DT16H", 184), ("P7D", 168)])
def test_parse_interval_durations(text, hours):
    start, dur = nws.parse_interval(f"2026-11-21T09:00:00+00:00/{text}")
    assert start == datetime(2026, 11, 21, 9, tzinfo=UTC) and dur == timedelta(hours=hours)


def test_gridpoint_conversion_units_and_hour_convention():
    t0 = datetime(2026, 12, 1, 0, tzinfo=UTC)
    props = {
        "validTimes": f"{iso(t0)}/PT12H",
        "windSpeed": {"values": [
            {"validTime": f"{iso(t0)}/PT4H", "value": 16.09344},               # 10 mph
            {"validTime": f"{iso(t0 + timedelta(hours=4))}/PT8H", "value": 80.4672},  # 50 mph
        ]},
        "windGust": {"values": []},
        "quantitativePrecipitation": {"values": [
            {"validTime": f"{iso(t0)}/PT6H", "value": 15.24},                   # 0.6 in over 6 h = 0.10 in/hr
            {"validTime": f"{iso(t0 + timedelta(hours=6))}/PT6H", "value": None},  # no forecast
        ]},
        "snowfallAmount": {"values": [{"validTime": f"{iso(t0)}/PT6H", "value": 76.2}]},  # 3 in / 6 h = 0.5 in/hr
    }
    s = nws.parse_gridpoint(props)
    assert s.start == t0 and len(s) == 13
    assert s.wind[0] == pytest.approx(10.0) and s.wind[3] == pytest.approx(10.0) and s.wind[4] == pytest.approx(50.0)
    # slot H holds the precipitation of the hour ending at H (Open-Meteo convention)
    assert s.rain[0] is None  # hour before the forecast starts: unknown, not zero
    assert s.rain[1] == pytest.approx(0.10) and s.rain[6] == pytest.approx(0.10)
    assert s.rain[7] is None  # null interval stays missing
    assert s.snow[3] == pytest.approx(0.5)
    assert all(g is None for g in s.gust)


def test_wind_conversion_keeps_the_exact_risk_boundaries():
    for kmh, expected in ((40.2336, RiskLevel.MODERATE), (88.51392, RiskLevel.NO_TRAVEL), (72.42048, RiskLevel.SEVERE)):
        mph = round(kmh / KMH_PER_MPH, 2)  # 25, 55, 45 mph exactly
        assert assess(mph, 0.0, 0.0, 20_000).level is expected


@pytest.mark.parametrize("lat,lon,us", [
    (40.71, -74.01, True), (61.22, -149.90, True), (21.31, -157.86, True), (18.47, -66.11, True),
    (19.43, -99.13, False), (51.51, -0.13, False), (35.0, -50.0, False), (45.42, -75.70, True),
])
def test_us_bounds_prefilter(lat, lon, us):
    # (45.42, -75.70) is Ottawa: inside the coarse lower-48 box, so weather.gov's 404 decides it
    assert nws.in_us_bounds(lat, lon) is us


# ---------------------------------------------------------------------------
# get_series: fallback behaviour, caching, non-US, failures
# ---------------------------------------------------------------------------
def soon():
    return datetime.now(UTC) + timedelta(hours=30)


US_POINTS = [(40.70, -74.00), (41.25, -73.10), (42.35, -71.05)]


def test_open_meteo_ok_means_weather_gov_is_never_called(rsps, fallback_on):
    rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=helpers.open_meteo_callback(),
                      content_type="application/json")
    fake = FakeNws(rsps)
    lookup = service.get_series(US_POINTS, soon())
    assert all(lookup.series) and lookup.fallback_locations == 0 and fake.calls == []


def test_fallback_fills_us_points_with_real_nws_values(rsps, fallback_on):
    open_meteo_429(rsps)
    fake = FakeNws(rsps, wind_kmh=80.4672, qpf_mm_6h=15.24)  # 50 mph, 0.10 in/hr
    lookup = service.get_series(US_POINTS, soon())
    assert lookup.fallback_locations == 3 and lookup.failed_locations == 0
    sample = sample_series(lookup.series[0], datetime.now(UTC) + timedelta(hours=2))
    assert sample.status == OK
    assert sample.wind_mph == pytest.approx(50.0) and sample.rain_in_hr == pytest.approx(0.10)
    assert lookup.errors and "HTTP 429" in lookup.errors[0]
    # weather.gov requirements: descriptive User-Agent + geo+json, documented two-step flow
    for req in fake.calls:
        assert req.headers["User-Agent"] == "haulwise-test/1.0 (contact: ops@example.com)"
        assert req.headers["Accept"] == "application/geo+json"
    assert fake.count("points") == 3 and fake.count("gridpoints") == 3


def test_points_and_grids_are_cached_and_shared(rsps, fallback_on):
    open_meteo_429(rsps)
    fake = FakeNws(rsps)
    # two checkpoints in the same ~2.5 km grid cell -> one gridpoint request
    service.get_series([(40.700, -74.000), (40.701, -74.001), (42.35, -71.05)], soon())
    first = (fake.count("points"), fake.count("gridpoints"))
    service.get_series([(40.700, -74.000), (42.35, -71.05)], soon())  # repeat analysis
    assert first == (2, 2) or first[1] < first[0]
    assert (fake.count("points"), fake.count("gridpoints")) == first  # nothing new requested


def test_open_meteo_is_paused_after_a_429(rsps, fallback_on):
    om_calls = open_meteo_429(rsps)
    FakeNws(rsps)
    service.get_series(US_POINTS, soon())
    after_first = len(om_calls)
    lookup = service.get_series([(39.0, -77.0)], soon())  # new point, Open-Meteo would be needed
    assert len(om_calls) == after_first  # not called again during the cool-down
    assert lookup.fallback_locations == 1 and "paused" in lookup.errors[0]


def test_non_us_points_are_not_sent_to_weather_gov(rsps, fallback_on):
    open_meteo_429(rsps)
    fake = FakeNws(rsps)
    lookup = service.get_series([(19.43, -99.13), (51.51, -0.13), (35.0, -50.0)], soon())  # Mexico City, London, Atlantic
    assert fake.calls == []
    assert lookup.series == [None, None, None] and lookup.failed_locations == 3 and lookup.fallback_not_covered == 3


def test_point_inside_box_but_not_covered_is_unavailable_and_cached(rsps, fallback_on):
    open_meteo_429(rsps)
    fake = FakeNws(rsps, not_covered=lambda lat, lon: lat > 43.0)  # Toronto is inside the coarse box
    lookup = service.get_series([(43.65, -79.38), (40.70, -74.00)], soon())
    assert lookup.series[0] is None and lookup.series[1] is not None
    assert lookup.fallback_not_covered == 1
    n = fake.count("points")
    service.get_series([(43.65, -79.38)], soon())
    assert fake.count("points") == n  # the 404 is cached too


def test_weather_gov_failure_leaves_points_unavailable(rsps, fallback_on):
    open_meteo_429(rsps)
    FakeNws(rsps, grid_status=500)
    lookup = service.get_series(US_POINTS, soon())
    assert lookup.series == [None, None, None] and lookup.failed_locations == 3
    assert lookup.fallback_errors == ["weather.gov gridpoint error (HTTP 500)"]


def test_missing_nws_values_are_not_invented(rsps, fallback_on):
    open_meteo_429(rsps)
    FakeNws(rsps, nulls=True)
    lookup = service.get_series(US_POINTS[:1], soon())
    s = sample_series(lookup.series[0], datetime.now(UTC) + timedelta(hours=2))
    assert s.status == NO_DATA and s.wind_mph is None and s.rain_in_hr is None


def test_eta_beyond_weather_gov_horizon_is_unavailable(rsps, fallback_on):
    open_meteo_429(rsps)
    FakeNws(rsps, days=2)
    lookup = service.get_series(US_POINTS[:1], soon())
    assert sample_series(lookup.series[0], datetime.now(UTC) + timedelta(days=5)).status == "beyond_forecast_horizon"


def test_fallback_respects_the_time_budget(rsps, fallback_on, settings):
    open_meteo_429(rsps)
    fake = FakeNws(rsps)
    result = nws.fetch_points(US_POINTS, budget_s=0)
    assert result.series == {} and fake.calls == [] and "time budget exhausted" in result.errors


def test_fallback_disabled_by_setting(rsps, settings):
    settings.WEATHER_FALLBACK_NWS = False
    open_meteo_429(rsps)
    fake = FakeNws(rsps)
    assert service.get_series(US_POINTS, soon()).failed_locations == 3 and fake.calls == []


# ---------------------------------------------------------------------------
# end to end: the production scenario (Open-Meteo 429) through the API
# ---------------------------------------------------------------------------
def analyze(load):
    r = APIClient().post("/api/routes/analyze/", {
        "origin": {"label": "Chicago", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]},
        "destination": {"label": "Indianapolis", "lat": helpers.DEST[0], "lon": helpers.DEST[1]},
        "departure_time": (djtz.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:00:00.000Z"),
        "load_weight_lb": load,
        "interval_miles": 25,
    }, format="json")
    assert r.status_code == 201, r.content
    return r.json()


@pytest.mark.django_db
@pytest.mark.parametrize("load,level,label", [(20_000, 3, "Severe"), (35_000, 4, "No Travel")])
def test_analysis_uses_weather_gov_and_keeps_load_rules(rsps, fallback_on, load, level, label):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body())
    open_meteo_429(rsps)
    FakeNws(rsps, wind_kmh=80.4672)  # 50 mph everywhere: Severe, or No Travel above 30,000 lb
    data = analyze(load)
    ws = data["weather_stats"]
    assert ws["fallback_locations"] == ws["unique_locations"] and ws["failed_locations"] == 0
    assert ws["fallback_provider"] == nws.PROVIDER_NAME
    for route in data["routes"]:
        assert route["metrics"]["weather_coverage"] == 1.0
        for cp in route["checkpoints"]:
            assert cp["weather"]["status"] == "ok" and cp["weather"]["wind_mph"] == pytest.approx(50.0)
            assert cp["risk"]["level"] == level and cp["risk"]["label"] == label
    assert any("weather.gov" in w and "Open-Meteo was unavailable" in w for w in data["warnings"])
    assert data["recommendation"]["headline"]


@pytest.mark.django_db
def test_analysis_reports_both_causes_when_fallback_also_fails(rsps, fallback_on):
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body())
    open_meteo_429(rsps)
    FakeNws(rsps, grid_status=500)
    data = analyze(20_000)
    for route in data["routes"]:
        assert all(cp["weather"]["status"] == "provider_error" and cp["risk"] is None for cp in route["checkpoints"])
    warning = next(w for w in data["warnings"] if "could not be retrieved" in w)
    assert "HTTP 429" in warning and "weather.gov fallback: weather.gov gridpoint error (HTTP 500)" in warning


@pytest.mark.django_db
def test_no_api_key_in_logs_or_response_during_fallback(rsps, fallback_on, settings, caplog):
    settings.OPEN_METEO_API_KEY = "SECRET-KEY-123"
    rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body())
    open_meteo_429(rsps)
    FakeNws(rsps)
    with caplog.at_level("DEBUG"):
        r = APIClient().post("/api/routes/analyze/", {
            "origin": {"label": "A", "lat": helpers.ORIGIN[0], "lon": helpers.ORIGIN[1]},
            "destination": {"label": "B", "lat": helpers.DEST[0], "lon": helpers.DEST[1]},
            "departure_time": (djtz.now() + timedelta(hours=2)).isoformat(),
            "load_weight_lb": 1000, "interval_miles": 25,
        }, format="json")
    assert r.status_code == 201
    assert "SECRET-KEY-123" not in r.content.decode() and "SECRET-KEY-123" not in caplog.text


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# credentials never reach the logs (any logger, including tracebacks)
# ---------------------------------------------------------------------------
def test_log_redaction_covers_messages_args_and_tracebacks(caplog):
    import logging

    from config.log_redaction import redact

    assert redact("GET /v1/forecast?lat=1&apikey=abc123&x=2") == "GET /v1/forecast?lat=1&apikey=[REDACTED]&x=2"
    assert redact("POST /route?api_key=XYZ") == "POST /route?api_key=[REDACTED]"
    log = logging.getLogger("urllib3.connectionpool")
    with caplog.at_level("DEBUG"):
        log.warning("Retrying after connection broken by %r: %s", "reset", "/v1/forecast?apikey=TOPSECRET")
        try:
            raise ValueError("url: https://x/y?api_key=TOPSECRET2")
        except ValueError:
            logging.getLogger("app").exception("failed")
    assert "TOPSECRET" not in caplog.text and "[REDACTED]" in caplog.text
