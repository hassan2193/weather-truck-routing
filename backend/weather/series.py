"""Hourly forecast series and sampling at an arbitrary arrival time."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

HOUR = timedelta(hours=1)

# Sampling statuses
OK = "ok"
BEYOND_HORIZON = "beyond_forecast_horizon"
BEFORE_START = "before_forecast_start"
NO_DATA = "no_data"
PROVIDER_ERROR = "provider_error"


@dataclass
class HourlySeries:
    """Consecutive hourly values starting at ``start`` (UTC).

    ``rain``/``snow`` are *intensities* in inches over the hour that **ends** at
    the slot time (Open-Meteo reports precipitation as the sum of the preceding
    hour, which equals an in/hr rate). ``wind`` is the instantaneous 10 m wind
    speed in mph at the slot time. ``None`` marks a missing value.
    """

    start: datetime
    wind: list[float | None]
    gust: list[float | None]
    rain: list[float | None]
    snow: list[float | None]

    def __len__(self) -> int:
        return len(self.wind)

    @property
    def end(self) -> datetime:
        return self.start + HOUR * (len(self) - 1)

    def time_at(self, index: int) -> datetime:
        return self.start + HOUR * index


@dataclass(frozen=True)
class WeatherSample:
    """Weather for one place at one arrival time."""

    status: str
    valid_time: datetime | None = None  # forecast slot the wind value came from
    wind_mph: float | None = None
    gust_mph: float | None = None
    rain_in_hr: float | None = None
    snow_in_hr: float | None = None

    @property
    def available(self) -> bool:
        return self.status == OK


def _hours_from_start(series: HourlySeries, when: datetime) -> float:
    return (when - series.start).total_seconds() / 3600.0


def sample_series(series: HourlySeries | None, when: datetime) -> WeatherSample:
    """Weather at ``when`` for a place, or an honest "unavailable" status.

    * Wind (an instantaneous value) uses the nearest hourly slot.
    * Rain/snow (hourly totals that end at the slot time) use the slot whose
      hour *contains* ``when``, i.e. the next slot at or after it.
    * Outside the series (beyond the provider's forecast horizon, or before
      the series starts) nothing is invented: a status code is returned.
    """
    if series is None or len(series) == 0:
        return WeatherSample(PROVIDER_ERROR)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    h = _hours_from_start(series, when)
    last = len(series) - 1
    precip_i = int(math.ceil(h - 1e-9))  # slot whose preceding hour contains `when`
    if precip_i > last:
        return WeatherSample(BEYOND_HORIZON)
    if h < -0.5:
        return WeatherSample(BEFORE_START)
    wind_i = min(max(int(math.floor(h + 0.5)), 0), last)
    precip_i = max(precip_i, 0)
    wind, rain, snow = series.wind[wind_i], series.rain[precip_i], series.snow[precip_i]
    if wind is None and rain is None and snow is None:
        return WeatherSample(NO_DATA, valid_time=series.time_at(wind_i))
    return WeatherSample(
        OK,
        valid_time=series.time_at(wind_i),
        wind_mph=wind,
        gust_mph=series.gust[wind_i],
        rain_in_hr=rain,
        snow_in_hr=snow,
    )


def slot_sample(series: HourlySeries | None, index: int) -> WeatherSample:
    """Weather exactly at hourly slot ``index`` (used for forecast-slider snapshots)."""
    if series is None or len(series) == 0:
        return WeatherSample(PROVIDER_ERROR)
    if index < 0:
        return WeatherSample(BEFORE_START)
    if index >= len(series):
        return WeatherSample(BEYOND_HORIZON)
    wind, rain, snow = series.wind[index], series.rain[index], series.snow[index]
    if wind is None and rain is None and snow is None:
        return WeatherSample(NO_DATA, valid_time=series.time_at(index))
    return WeatherSample(
        OK, valid_time=series.time_at(index), wind_mph=wind, gust_mph=series.gust[index],
        rain_in_hr=rain, snow_in_hr=snow,
    )


def floor_to_hour(when: datetime) -> datetime:
    return when.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def parse_series(start: datetime, hourly: dict) -> HourlySeries:
    """Build a series from an Open-Meteo ``hourly`` block (rain+showers combined)."""
    n = len(hourly["time"])

    def col(name: str) -> list[float | None]:
        return list(hourly.get(name) or [None] * n)

    rain, showers = col("rain"), col("showers")
    combined = [
        None if r is None and s is None else (r or 0.0) + (s or 0.0) for r, s in zip(rain, showers)
    ]
    return HourlySeries(start=start, wind=col("wind_speed_10m"), gust=col("wind_gusts_10m"),
                        rain=combined, snow=col("snowfall"))
