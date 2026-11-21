"""Weather sampling at arrival time, missing data, and request de-duplication / caching."""
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.core.cache import cache

from weather import service
from weather.open_meteo import WeatherProviderError
from weather.series import (
    BEFORE_START,
    BEYOND_HORIZON,
    NO_DATA,
    OK,
    PROVIDER_ERROR,
    HourlySeries,
    floor_to_hour,
    sample_series,
    slot_sample,
)

T0 = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)


def make_series(n=24, start=T0, wind=None, rain=None, snow=None):
    return HourlySeries(
        start=start,
        wind=wind or [float(i) for i in range(n)],  # wind == hour index
        gust=[None] * n,
        rain=rain or [i / 100 for i in range(n)],  # rain == index / 100
        snow=snow or [0.0] * n,
    )


def test_sample_exact_hour():
    s = sample_series(make_series(), T0 + timedelta(hours=5))
    assert s.status == OK and s.wind_mph == 5 and s.rain_in_hr == 0.05 and s.valid_time == T0 + timedelta(hours=5)


def test_wind_uses_nearest_hour_and_precip_uses_containing_hour():
    # 05:20 -> nearest wind slot is 05:00; precipitation for 05:00-06:00 is reported at 06:00.
    s = sample_series(make_series(), T0 + timedelta(hours=5, minutes=20))
    assert s.wind_mph == 5 and s.rain_in_hr == 0.06
    # 05:40 -> nearest wind slot is 06:00
    s = sample_series(make_series(), T0 + timedelta(hours=5, minutes=40))
    assert s.wind_mph == 6 and s.rain_in_hr == 0.06


def test_weather_is_taken_at_arrival_time_not_departure():
    series = make_series()
    at_departure = sample_series(series, T0 + timedelta(hours=1))
    at_arrival = sample_series(series, T0 + timedelta(hours=1, minutes=300))
    assert at_departure.wind_mph != at_arrival.wind_mph and at_arrival.wind_mph == 6


def test_beyond_horizon_is_unavailable_not_invented():
    series = make_series(24)  # last slot is 23:00
    assert sample_series(series, T0 + timedelta(hours=23)).status == OK
    s = sample_series(series, T0 + timedelta(hours=23, minutes=30))
    assert s.status == BEYOND_HORIZON and s.wind_mph is None
    assert sample_series(series, T0 + timedelta(days=5)).status == BEYOND_HORIZON


def test_before_start_is_unavailable():
    assert sample_series(make_series(), T0 - timedelta(hours=3)).status == BEFORE_START


def test_missing_values_status():
    series = make_series(3, wind=[None] * 3, rain=[None] * 3, snow=[None] * 3)
    assert sample_series(series, T0 + timedelta(hours=1)).status == NO_DATA
    assert sample_series(None, T0).status == PROVIDER_ERROR


def test_partial_missing_values_are_kept_as_none():
    series = make_series(3, wind=[5.0, 6.0, 7.0], rain=[None, None, None], snow=[0.0, 0.0, 0.0])
    s = sample_series(series, T0 + timedelta(hours=1))
    assert s.status == OK and s.wind_mph == 6.0 and s.rain_in_hr is None


def test_naive_datetime_is_treated_as_utc():
    assert sample_series(make_series(), datetime(2026, 12, 1, 3)).wind_mph == 3


def test_slot_sample_and_bounds():
    series = make_series(4)
    assert slot_sample(series, 2).wind_mph == 2
    assert slot_sample(series, 4).status == BEYOND_HORIZON
    assert slot_sample(series, -1).status == BEFORE_START


def test_floor_to_hour():
    assert floor_to_hour(datetime(2026, 12, 1, 8, 47, 12, tzinfo=UTC)) == datetime(2026, 12, 1, 8, tzinfo=UTC)


# --- service: dedupe + cache ---------------------------------------------------------
def fake_fetch(coords, days, timeout=None):
    fake_fetch.calls.append(list(coords))
    start = floor_to_hour(datetime.now(UTC)) - timedelta(days=1)
    return [make_series(24 * 17, start=start) for _ in coords]


@pytest.fixture
def patched_fetch():
    fake_fetch.calls = []
    with mock.patch.object(service, "fetch_batch", side_effect=fake_fetch):
        yield fake_fetch


def soon():
    return datetime.now(UTC) + timedelta(hours=30)


def test_nearby_points_share_one_upstream_location(patched_fetch):
    pts = [(40.001, -100.001), (40.012, -100.01), (40.02, -99.99), (41.0, -100.0)]
    lookup = service.get_series(pts, soon())
    assert lookup.unique_locations == 2
    assert sum(len(c) for c in patched_fetch.calls) == 2
    assert lookup.series[0] is lookup.series[1] is lookup.series[2]
    assert len(lookup.series) == 4


def test_second_lookup_is_served_from_cache(patched_fetch):
    pts = [(40.0, -100.0), (41.0, -100.0)]
    service.get_series(pts, soon())
    again = service.get_series(pts, soon())
    assert len(patched_fetch.calls) == 1
    assert again.cache_hits == 2 and again.upstream_requests == 0


def test_requests_are_batched(patched_fetch, settings):
    settings.WEATHER_BATCH_SIZE = 10
    pts = [(30 + i * 0.5, -100.0) for i in range(25)]
    lookup = service.get_series(pts, soon())
    assert lookup.upstream_requests == 3
    assert sorted(len(c) for c in patched_fetch.calls) == [5, 10, 10]


def test_cached_series_that_is_too_short_is_refetched(patched_fetch):
    short = make_series(24, start=floor_to_hour(datetime.now(UTC)))
    cache.set(service._cache_key(service.snap(45.0, -100.0)), short, 600)
    service.get_series([(45.0, -100.0)], datetime.now(UTC) + timedelta(days=5))
    assert len(patched_fetch.calls) == 1


def test_provider_failure_marks_points_unavailable_without_crashing():
    with mock.patch.object(service, "fetch_batch", side_effect=WeatherProviderError("boom")):
        lookup = service.get_series([(40.0, -100.0), (41.0, -100.0)], soon())
    assert lookup.series == [None, None]
    assert lookup.failed_locations == 2 and lookup.errors == ["boom"]
    assert sample_series(lookup.series[0], datetime.now(UTC)).status == PROVIDER_ERROR


def test_failed_results_are_not_cached():
    with mock.patch.object(service, "fetch_batch", side_effect=WeatherProviderError("boom")):
        service.get_series([(40.0, -100.0)], soon())
    fake_fetch.calls = []
    with mock.patch.object(service, "fetch_batch", side_effect=fake_fetch):
        lookup = service.get_series([(40.0, -100.0)], soon())
    assert lookup.series[0] is not None and len(fake_fetch.calls) == 1
