"""Open-Meteo client: batched hourly forecasts for many coordinates."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import requests
from django.conf import settings

from config.http import get_session

from .series import HourlySeries, parse_series

logger = logging.getLogger(__name__)

HOURLY_VARIABLES = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
PAST_DAYS = 1


class WeatherProviderError(Exception):
    """Open-Meteo could not be reached or rejected the request."""


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def fetch_batch(coords: Sequence[tuple[float, float]], forecast_days: int) -> list[HourlySeries]:
    """Fetch hourly series for up to ~100 coordinates in a single request.

    Units are requested server-side (mph, inches) and times in GMT so no
    conversion is done here. Order of the result matches ``coords``.
    """
    if not coords:
        return []
    params = {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
        "hourly": HOURLY_VARIABLES,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "past_days": PAST_DAYS,
        "forecast_days": max(1, min(settings.WEATHER_MAX_FORECAST_DAYS, forecast_days)),
    }
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
    try:
        resp = get_session().get(settings.OPEN_METEO_URL, params=params, timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise WeatherProviderError(f"Weather service unreachable: {exc}") from exc
    if resp.status_code != 200:
        reason = ""
        try:
            reason = resp.json().get("reason", "")
        except ValueError:
            pass
        raise WeatherProviderError(f"Weather service error (HTTP {resp.status_code}) {reason}".strip())
    try:
        payload = resp.json()
        items = payload if isinstance(payload, list) else [payload]
        series = [parse_series(_parse_time(item["hourly"]["time"][0]), item["hourly"]) for item in items]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise WeatherProviderError("Weather service returned an unexpected response") from exc
    if len(series) != len(coords):
        raise WeatherProviderError("Weather service returned a different number of locations than requested")
    return series
