"""Open-Meteo client: batched hourly forecasts for many coordinates."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import requests
from django.conf import settings

from config.http import get_session, timeouts

from .series import HourlySeries, parse_series

logger = logging.getLogger(__name__)

HOURLY_VARIABLES = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
PAST_DAYS = 1


class WeatherProviderError(Exception):
    """Open-Meteo could not be reached or rejected the request."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def fetch_batch(
    coords: Sequence[tuple[float, float]], forecast_days: int, timeout: float | None = None
) -> list[HourlySeries]:
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
        read_timeout = timeout or settings.HTTP_TIMEOUT_SECONDS
        resp = get_session().get(settings.OPEN_METEO_URL, params=params, timeout=timeouts(read_timeout))
    except requests.RequestException as exc:
        # Never put str(exc) in the message: it contains the request URL, including the API key.
        kind = "timed out" if isinstance(exc, requests.Timeout) else "could not be reached"
        logger.warning("Open-Meteo request %s (%s)", kind, type(exc).__name__)
        raise WeatherProviderError(f"Weather service {kind} ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        reason = ""
        try:
            reason = str(resp.json().get("reason", ""))[:200]
        except ValueError:
            pass
        # Open-Meteo explains failures in "reason" (e.g. rate limits, invalid API key); keep it.
        raise WeatherProviderError(
            f"Weather service error (HTTP {resp.status_code}){': ' + reason if reason else ''}", resp.status_code
        )
    try:
        payload = resp.json()
        items = payload if isinstance(payload, list) else [payload]
        series = [parse_series(_parse_time(item["hourly"]["time"][0]), item["hourly"]) for item in items]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise WeatherProviderError("Weather service returned an unexpected response") from exc
    if len(series) != len(coords):
        raise WeatherProviderError("Weather service returned a different number of locations than requested")
    return series
