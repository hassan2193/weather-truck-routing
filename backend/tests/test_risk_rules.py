"""Risk classification: exact threshold boundaries and the load-specific rules."""
import pytest

from risk_engine.levels import RiskLevel as L
from risk_engine.rules import assess, classify_rain, classify_snow, classify_wind, classify_wind_for_load


@pytest.mark.parametrize("mph,expected", [
    (0, L.LOW), (24.9, L.LOW), (24.99, L.LOW),
    (25, L.MODERATE), (30, L.MODERATE), (34, L.MODERATE), (34.9, L.MODERATE), (34.99, L.MODERATE),
    (35, L.HIGH), (44, L.HIGH), (44.9, L.HIGH),
    (45, L.SEVERE), (54, L.SEVERE), (54.9, L.SEVERE),
    (55, L.NO_TRAVEL), (55.1, L.NO_TRAVEL), (90, L.NO_TRAVEL),
])
def test_wind_thresholds(mph, expected):
    assert classify_wind(mph) is expected


@pytest.mark.parametrize("rate,expected", [
    (0, L.LOW), (0.05, L.LOW), (0.099, L.LOW),
    (0.10, L.MODERATE), (0.2, L.MODERATE), (0.249, L.MODERATE),
    (0.25, L.HIGH), (0.499, L.HIGH),            # 0.25 is shared by the PDF's bands: lower bound wins
    (0.50, L.SEVERE), (0.75, L.SEVERE), (1.00, L.SEVERE),  # "No Travel is > 1.00" so 1.00 is Severe
    (1.001, L.NO_TRAVEL), (3.0, L.NO_TRAVEL),
])
def test_rain_thresholds(rate, expected):
    assert classify_rain(rate) is expected


@pytest.mark.parametrize("rate,expected", [
    (0, L.LOW), (0.49, L.LOW), (0.499, L.LOW),
    (0.5, L.MODERATE), (0.99, L.MODERATE),
    (1.0, L.HIGH), (1.99, L.HIGH),
    (2.0, L.SEVERE), (3.0, L.SEVERE),          # "No Travel is > 3.0" so 3.0 is Severe
    (3.001, L.NO_TRAVEL), (8, L.NO_TRAVEL),
])
def test_snow_thresholds(rate, expected):
    assert classify_snow(rate) is expected


def test_levels_are_ordered_low_to_no_travel():
    assert L.LOW < L.MODERATE < L.HIGH < L.SEVERE < L.NO_TRAVEL
    assert [l.label for l in L] == ["Low", "Moderate", "High", "Severe", "No Travel"]


# --- load rules ---------------------------------------------------------------
@pytest.mark.parametrize("load", [0, 10_000, 30_000, 40_000, 45_000, 80_000])
def test_wind_55_is_no_travel_for_any_load(load):
    assert classify_wind_for_load(55, load)[0] is L.NO_TRAVEL
    assert classify_wind_for_load(70, load)[0] is L.NO_TRAVEL


@pytest.mark.parametrize("wind", [45, 50, 54, 54.9])
def test_wind_45_54_heavy_load_is_no_travel(wind):
    level, rule = classify_wind_for_load(wind, 30_001)
    assert level is L.NO_TRAVEL and rule


@pytest.mark.parametrize("wind", [45, 50, 54])
def test_wind_45_54_at_exactly_30000_lb_is_not_escalated(wind):
    level, rule = classify_wind_for_load(wind, 30_000)  # rule is "> 30,000"
    assert level is L.SEVERE and rule is None


@pytest.mark.parametrize("wind", [35, 40, 44, 44.9])
def test_wind_35_44_over_40000_lb_is_severe(wind):
    level, rule = classify_wind_for_load(wind, 40_001)
    assert level is L.SEVERE and rule


@pytest.mark.parametrize("wind", [35, 40, 44])
def test_wind_35_44_at_exactly_40000_lb_stays_high(wind):
    level, rule = classify_wind_for_load(wind, 40_000)  # rule is "> 40,000"
    assert level is L.HIGH and rule is None


def test_load_does_not_affect_lighter_wind():
    assert classify_wind_for_load(34.9, 80_000)[0] is L.MODERATE
    assert classify_wind_for_load(10, 80_000)[0] is L.LOW


def test_load_rule_between_30000_and_40000_only_matters_for_45_plus():
    # 35-44 mph with 35,000 lb: stays High; 45-54 with 35,000 lb: No Travel.
    assert classify_wind_for_load(40, 35_000)[0] is L.HIGH
    assert classify_wind_for_load(50, 35_000)[0] is L.NO_TRAVEL


# --- combined assessment ---------------------------------------------------------
def test_assess_takes_highest_of_wind_rain_snow():
    a = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=2.5, load_lb=20_000)
    assert a.level is L.SEVERE
    assert (a.wind_level, a.rain_level, a.snow_level) == (L.LOW, L.HIGH, L.SEVERE)
    assert any("Snow" in d for d in a.drivers)


def test_assess_applies_load_rule_then_max():
    a = assess(40, 0.12, 0, load_lb=45_000)  # wind High->Severe by load, rain Moderate
    assert a.level is L.SEVERE and a.load_rule
    b = assess(40, 0.12, 0, load_lb=20_000)
    assert b.level is L.HIGH and b.load_rule is None


def test_assess_all_low():
    a = assess(5, 0, 0, 50_000)
    assert a.level is L.LOW and a.drivers == ()


def test_assess_missing_data_is_not_assumed_low():
    assert assess(None, None, None, 10_000) is None


def test_assess_partial_data_uses_what_is_available():
    a = assess(wind_mph=60, rain_in_hr=None, snow_in_hr=None, load_lb=1_000)
    assert a.level is L.NO_TRAVEL and a.partial
    b = assess(wind_mph=None, rain_in_hr=0.6, snow_in_hr=None, load_lb=1_000)
    assert b.level is L.SEVERE and b.partial


@pytest.mark.parametrize("bad", [-1, float("nan")])
def test_invalid_values_rejected(bad):
    with pytest.raises(ValueError):
        classify_wind(bad)
    with pytest.raises(ValueError):
        classify_rain(bad)
    with pytest.raises(ValueError):
        classify_snow(bad)


def test_negative_load_rejected():
    with pytest.raises(ValueError):
        classify_wind_for_load(40, -5)
