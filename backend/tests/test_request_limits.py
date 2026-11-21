"""Regression tests for the production analyze failure (requests hanging past 120 s).

Root cause: provider calls retried timed-out POSTs and obeyed long Retry-After headers,
so one analysis could block a gunicorn worker for minutes (killed at 120 s; the browser
gave up at 120 s too). These tests use *real* local HTTP servers for the provider
failure modes, so urllib3's actual retry/timeout behaviour is exercised, not a mock.
"""
import json
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import responses
from django.conf import settings
from rest_framework.test import APIClient

from routing import route_search, valhalla
from weather import service as weather_service

from . import helpers

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[2]


def frontend_payload():
    """The exact request body the deployed frontend sent (TripForm.jsx -> api/client.js)."""
    departure = (datetime.now(UTC) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    return {
        "origin": {"label": "Chicago, Cook County, Illinois, United States", "lat": 41.8755616, "lon": -87.6244212},
        "destination": {
            "label": "Indianapolis, Marion County, Indiana, United States", "lat": 39.7683331, "lon": -86.1583502,
        },
        # Date.prototype.toISOString(): millisecond precision, "Z" suffix
        "departure_time": departure.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "load_weight_lb": 42000,
        "interval_miles": 25,
    }


def post(payload):
    started = time.monotonic()
    r = APIClient().post("/api/routes/analyze/", payload, format="json")
    return r, time.monotonic() - started


# ---------------------------------------------------------------------------
# real local servers that misbehave like an overloaded / throttling provider
# ---------------------------------------------------------------------------
class _Provider:
    def __init__(self, handler_body):
        self.requests = 0
        self.release = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests += 1
                handler_body(self, outer)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


def _never_answer(handler, provider):
    provider.release.wait(15)  # hold the connection open without replying


def _rate_limit(handler, provider):
    body = b'{"error": "rate limited"}'
    handler.send_response(429)
    handler.send_header("Retry-After", "40")
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@pytest.fixture
def hanging_valhalla(settings, monkeypatch):
    provider = _Provider(_never_answer)
    settings.VALHALLA_URL = provider.url
    settings.ROUTING_TIMEOUT_SECONDS = 1.0
    monkeypatch.setattr(route_search, "MIN_ATTEMPT_S", 0.5)
    yield provider
    provider.close()


@pytest.fixture
def throttling_valhalla(settings):
    provider = _Provider(_rate_limit)
    settings.VALHALLA_URL = provider.url
    yield provider
    provider.close()


# ---------------------------------------------------------------------------
# the exact failing payload
# ---------------------------------------------------------------------------
def test_exact_frontend_payload_is_valid_and_analysed():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        helpers.install(rsps)
        r, _ = post(frontend_payload())
    assert r.status_code == 201, r.content
    assert len(r.json()["routes"]) == 3


def test_unresponsive_routing_provider_fails_fast_without_retrying(hanging_valhalla):
    r, elapsed = post(frontend_payload())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "routing_unavailable"
    assert "did not respond within 1 seconds" in r.json()["error"]["message"]
    assert hanging_valhalla.requests == 1  # a timed-out POST is not retried
    assert elapsed < 5  # was: 4 x read timeout (360 s with production defaults)


def test_rate_limited_routing_provider_does_not_sleep_on_retry_after(throttling_valhalla):
    r, elapsed = post(frontend_payload())
    assert r.status_code == 502
    assert "rate-limiting" in r.json()["error"]["message"]
    assert throttling_valhalla.requests <= 3  # at most 2 short retries
    assert elapsed < 8  # was: 3 x Retry-After 40 s = 120 s


# ---------------------------------------------------------------------------
# the whole analysis stays inside its deadline
# ---------------------------------------------------------------------------
@pytest.fixture
def spy_timeouts(monkeypatch):
    seen = {"routing": [], "weather": []}
    real_request, real_fetch = valhalla.request_routes, weather_service.fetch_batch

    def request_routes(*args, **kwargs):
        seen["routing"].append(kwargs.get("timeout"))
        return real_request(*args, **kwargs)

    def fetch_batch(coords, days, timeout=None):
        seen["weather"].append(timeout)
        return real_fetch(coords, days, timeout)

    monkeypatch.setattr(valhalla, "request_routes", request_routes)
    monkeypatch.setattr(weather_service, "fetch_batch", fetch_batch)
    return seen


def test_every_provider_call_is_bounded_by_the_deadline(spy_timeouts):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # 1 direct route -> re-routing attempts happen, all must respect the budget
        rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body(bulges=(0.0,)))
        rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=helpers.open_meteo_callback(),
                          content_type="application/json")
        r, _ = post(frontend_payload())
    assert r.status_code == 201
    budget = settings.ANALYSIS_DEADLINE_SECONDS - route_search.WEATHER_RESERVE_S
    assert spy_timeouts["routing"] and all(0 < t <= budget for t in spy_timeouts["routing"])
    assert spy_timeouts["routing"][0] == settings.ROUTING_TIMEOUT_SECONDS
    assert spy_timeouts["weather"] and all(0 < t <= settings.HTTP_TIMEOUT_SECONDS for t in spy_timeouts["weather"])


def test_alternatives_are_skipped_when_the_deadline_is_nearly_spent(settings, spy_timeouts):
    settings.ANALYSIS_DEADLINE_SECONDS = route_search.WEATHER_RESERVE_S + 2  # too little left for re-routing
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", json=helpers.valhalla_body(bulges=(0.0,)))
        rsps.add_callback(responses.GET, settings.OPEN_METEO_URL, callback=helpers.open_meteo_callback(),
                          content_type="application/json")
        r, _ = post(frontend_payload())
    assert r.status_code == 201  # still answers, with what it has
    assert r.json()["route_search"]["attempts"] == 0
    assert len(spy_timeouts["routing"]) == 1
    assert "Only 1 genuinely distinct truck route" in r.json()["route_search"]["message"]


def test_deadline_is_below_server_and_browser_timeouts():
    gunicorn = int(re.search(r"--timeout (\d+)", (ROOT / "Dockerfile").read_text()).group(1))
    client_js = (ROOT / "frontend" / "src" / "api" / "client.js").read_text(encoding="utf-8")
    browser_ms = int(re.search(r"timeoutMs = (\d+)", client_js).group(1))
    deadline = settings.ANALYSIS_DEADLINE_SECONDS
    # leave room for geocoding free text and saving the result after the provider calls
    assert deadline + 15 <= gunicorn
    assert deadline + 15 <= browser_ms / 1000


# ---------------------------------------------------------------------------
# a 422 now says why in the server log
# ---------------------------------------------------------------------------
def test_reason_for_a_422_is_logged(caplog):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.POST, f"{settings.VALHALLA_URL}/route", status=400,
                 json={"error_code": 442, "error": "No path could be found for input"})
        with caplog.at_level("WARNING", logger="api.exceptions"):
            r, _ = post(frontend_payload())
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_route"
    assert "error 442: No path could be found for input" in r.json()["error"]["message"]
    assert any("422 no_route" in m and "error 442" in m for m in caplog.messages)


def test_payload_json_matches_frontend_field_names():
    form = (ROOT / "frontend" / "src" / "components" / "TripForm.jsx").read_text(encoding="utf-8")
    sent = set(re.findall(r"^\s+(\w+): ", form[form.index("onSubmit({"):form.index("})", form.index("onSubmit({"))], re.M))
    assert sent == set(frontend_payload()) == {"origin", "destination", "departure_time", "load_weight_lb", "interval_miles"}
    assert json.dumps(frontend_payload())  # serialisable as sent
