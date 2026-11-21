"""Live integration test against the real Valhalla, Open-Meteo and Photon services.

Skipped by default so CI stays deterministic and polite to free public APIs.
Run with:  RUN_LIVE_TESTS=1 pytest tests/test_live.py
"""
import os
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.django_db,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to hit real APIs"),
]


def test_real_trip_end_to_end():
    client = APIClient()
    r = client.post("/api/routes/analyze/", {
        "origin": "Chicago, IL",
        "destination": "Indianapolis, IN",
        "departure_time": (timezone.now() + timedelta(hours=3)).isoformat(),
        "load_weight_lb": 42_000,
        "interval_miles": 25,
    }, format="json")
    assert r.status_code == 201, r.content
    data = r.json()
    assert 1 <= len(data["routes"]) <= 3
    for route in data["routes"]:
        assert 150 < route["distance_mi"] < 260  # Chicago -> Indianapolis is ~185 mi by road
        assert 2 * 3600 < route["duration_s"] < 6 * 3600
        ok = [c for c in route["checkpoints"] if c["weather"]["status"] == "ok"]
        assert len(ok) == len(route["checkpoints"])
        assert all(0 <= c["weather"]["wind_mph"] < 120 for c in ok)
        assert all(c["risk"]["label"] for c in ok)
    f = client.get(f"/api/routes/{data['routes'][0]['id']}/forecast/").json()
    assert len(f["hours"]) == 49 and f["heat"]
    assert client.get("/api/geocode/", {"q": "Dallas"}).json()["results"]
