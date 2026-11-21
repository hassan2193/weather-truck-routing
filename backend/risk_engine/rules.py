"""Weather risk classification and load-specific rules.

Threshold interpretation
------------------------
The assessment PDF writes ranges such as ``25-34`` mph or ``0.10-0.25`` in/hr.
Those notations leave gaps for fractional values (34.5 mph) and overlap at the
shared endpoints of the rain/snow bands (0.25 in/hr is both the top of
Moderate and the bottom of High). To make classification total and
deterministic we use these rules, applied identically to wind, rain and snow:

* Every band is **lower-bound inclusive and upper-bound exclusive**: ``[lo, hi)``.
  So 35 mph is High (not Moderate), 0.25 in/hr is High, 0.5 in/hr snow is
  Moderate, and 55 mph is No Travel.
* The ``Low`` band is "strictly less than" its limit (``<25``, ``<0.10``, ``<0.5``),
  which agrees with the rule above.
* Where the PDF's No Travel band is written with a *strict* ``>`` (rain
  ``>1.00``, snow ``>3.0``) the boundary value itself belongs to **Severe**
  (the PDF lists ``0.50-1.00`` and ``2.0-3.0`` as the Severe bands, so their
  closed upper end is Severe). Wind's No Travel band is ``>=55``, so 55 is
  No Travel.

Load rules (load compared with strict ``>`` as written in the PDF):

* wind >= 55 mph                  -> No Travel (any load)
* 45 <= wind < 55 and load > 30,000 lb -> No Travel
* 35 <= wind < 45 and load > 40,000 lb -> Severe

Load rules can only *raise* the wind classification, and the checkpoint's final
level is the highest level across wind, rain and snow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .levels import RiskLevel

# ---------------------------------------------------------------------------
# Threshold tables
# ---------------------------------------------------------------------------
# Each table lists the *lower inclusive bound* at which a level starts, from
# the lowest level upwards. A value is classified as the highest level whose
# bound it reaches. ``strict_top`` marks tables whose No Travel band is a
# strict ``>`` (so the bound itself still belongs to Severe).

WIND_BOUNDS = (
    (RiskLevel.MODERATE, 25.0),
    (RiskLevel.HIGH, 35.0),
    (RiskLevel.SEVERE, 45.0),
    (RiskLevel.NO_TRAVEL, 55.0),
)
RAIN_BOUNDS = (
    (RiskLevel.MODERATE, 0.10),
    (RiskLevel.HIGH, 0.25),
    (RiskLevel.SEVERE, 0.50),
    (RiskLevel.NO_TRAVEL, 1.00),
)
SNOW_BOUNDS = (
    (RiskLevel.MODERATE, 0.5),
    (RiskLevel.HIGH, 1.0),
    (RiskLevel.SEVERE, 2.0),
    (RiskLevel.NO_TRAVEL, 3.0),
)

# Load rules.
LOAD_NO_TRAVEL_WIND_LOAD_LB = 30_000  # wind 45-54 mph and load above this -> No Travel
LOAD_SEVERE_WIND_LOAD_LB = 40_000  # wind 35-44 mph and load above this -> Severe


def _classify(value: float, bounds, *, strict_top: bool) -> RiskLevel:
    level = RiskLevel.LOW
    for lvl, lower in bounds:
        if lvl is RiskLevel.NO_TRAVEL and strict_top:
            reached = value > lower
        else:
            reached = value >= lower
        if reached:
            level = lvl
    return level


def _check(name: str, value: float) -> float:
    if value is None or isinstance(value, bool) or math.isnan(value):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value!r}")
    return float(value)


def classify_wind(mph: float) -> RiskLevel:
    """Classify sustained wind speed (mph) ignoring load."""
    return _classify(_check("wind", mph), WIND_BOUNDS, strict_top=False)


def classify_rain(inches_per_hour: float) -> RiskLevel:
    """Classify rainfall intensity (in/hr)."""
    return _classify(_check("rain", inches_per_hour), RAIN_BOUNDS, strict_top=True)


def classify_snow(inches_per_hour: float) -> RiskLevel:
    """Classify snowfall intensity (in/hr)."""
    return _classify(_check("snow", inches_per_hour), SNOW_BOUNDS, strict_top=True)


def classify_wind_for_load(mph: float, load_lb: float) -> tuple[RiskLevel, str | None]:
    """Classify wind applying the load-specific rules.

    Returns ``(level, rule_description)``; ``rule_description`` is ``None``
    when the load did not change the result.
    """
    load = _check("load", load_lb)
    base = classify_wind(mph)
    if base is RiskLevel.SEVERE and load > LOAD_NO_TRAVEL_WIND_LOAD_LB:
        return RiskLevel.NO_TRAVEL, (
            f"Wind 45-54 mph with a load over {LOAD_NO_TRAVEL_WIND_LOAD_LB:,} lb is No Travel"
        )
    if base is RiskLevel.HIGH and load > LOAD_SEVERE_WIND_LOAD_LB:
        return RiskLevel.SEVERE, (
            f"Wind 35-44 mph with a load over {LOAD_SEVERE_WIND_LOAD_LB:,} lb is Severe"
        )
    return base, None


# ---------------------------------------------------------------------------
# Checkpoint assessment
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskAssessment:
    """Result of assessing one checkpoint (or one forecast hour)."""

    level: RiskLevel
    wind_level: RiskLevel | None
    rain_level: RiskLevel | None
    snow_level: RiskLevel | None
    load_rule: str | None = None
    # Human readable explanation of what drives ``level``.
    drivers: tuple[str, ...] = field(default_factory=tuple)
    # True when at least one of the three inputs was missing.
    partial: bool = False


def assess(
    wind_mph: float | None,
    rain_in_hr: float | None,
    snow_in_hr: float | None,
    load_lb: float,
) -> RiskAssessment | None:
    """Assess weather risk at one place and time for a given load.

    Missing (``None``) inputs are skipped rather than assumed to be zero. If
    *all* inputs are missing there is nothing to assess and ``None`` is
    returned so callers can show an "unavailable" status instead of a made-up
    "Low".
    """
    if wind_mph is None and rain_in_hr is None and snow_in_hr is None:
        return None

    wind_level = rain_level = snow_level = None
    load_rule = None
    drivers: list[str] = []

    if wind_mph is not None:
        wind_level, load_rule = classify_wind_for_load(wind_mph, load_lb)
        if wind_level > RiskLevel.LOW:
            note = f" ({load_rule})" if load_rule else ""
            drivers.append(f"Wind {wind_mph:.0f} mph → {wind_level.label}{note}")
    if rain_in_hr is not None:
        rain_level = classify_rain(rain_in_hr)
        if rain_level > RiskLevel.LOW:
            drivers.append(f"Rain {rain_in_hr:.2f} in/hr → {rain_level.label}")
    if snow_in_hr is not None:
        snow_level = classify_snow(snow_in_hr)
        if snow_level > RiskLevel.LOW:
            drivers.append(f"Snow {snow_in_hr:.2f} in/hr → {snow_level.label}")

    present = [lvl for lvl in (wind_level, rain_level, snow_level) if lvl is not None]
    return RiskAssessment(
        level=max(present),
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_rule=load_rule,
        drivers=tuple(drivers),
        partial=len(present) < 3,
    )
