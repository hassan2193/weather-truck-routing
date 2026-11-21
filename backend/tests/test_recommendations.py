"""Risk-mile calculation, lexicographic ranking, the No Travel gate and explanations."""
import pytest

from recommendations.engine import rank_routes
from recommendations.explain import build_recommendation
from recommendations.metrics import Segment, compute_metrics
from risk_engine.levels import RiskLevel as L

LABELS = {"a": "Route A", "b": "Route B", "c": "Route C"}


def metrics(segments, distance=None, duration=3600.0):
    segs = [Segment(m, lvl) for m, lvl in segments]
    return compute_metrics(segs, distance if distance is not None else sum(sg.miles for sg in segs), duration)


def order(**routes):
    return [r.key for r in rank_routes(routes)]


# --- risk miles ---------------------------------------------------------------------
def test_risk_miles_use_segment_length_not_checkpoint_count():
    m = metrics([(5, L.LOW), (50, L.SEVERE), (45, L.LOW)])  # 3 checkpoints, 50 severe miles
    assert m.severe_miles == 50 and m.low_miles == 50 and m.high_miles == 0
    # a single High checkpoint representing 10 miles vs three checkpoints of 1 mile each
    assert metrics([(10, L.HIGH)]).high_miles == 10
    assert metrics([(1, L.HIGH)] * 3).high_miles == 3


def test_average_risk_is_distance_weighted():
    m = metrics([(75, L.LOW), (25, L.SEVERE)])  # (0*75 + 3*25)/100
    assert m.average_risk == pytest.approx(0.75)
    n = metrics([(10, L.NO_TRAVEL), (10, L.MODERATE)])
    assert n.average_risk == pytest.approx(2.5)


def test_unknown_weather_is_not_counted_as_low():
    m = metrics([(40, L.LOW), (60, None)])
    assert m.low_miles == 40 and m.unknown_miles == 60
    assert m.average_risk == 0 and m.coverage == pytest.approx(0.4)
    none = metrics([(10, None)])
    assert none.average_risk is None and none.assessed_miles == 0


# --- ranking: lexicographic priority ------------------------------------------------------
def test_fewest_severe_miles_wins_over_everything_else():
    a = metrics([(100, L.LOW), (10, L.SEVERE)], duration=1000)   # fastest, 10 severe
    b = metrics([(100, L.HIGH), (10, L.HIGH)], duration=9000)    # slow, lots of High, 0 severe
    assert order(a=a, b=b) == ["b", "a"]


def test_high_miles_break_a_severe_tie():
    a = metrics([(50, L.HIGH), (50, L.LOW)], duration=1000)
    b = metrics([(10, L.HIGH), (90, L.MODERATE)], duration=9000)
    assert order(a=a, b=b) == ["b", "a"]


def test_average_risk_breaks_a_severe_and_high_tie():
    a = metrics([(50, L.MODERATE), (50, L.LOW)], duration=1000)
    b = metrics([(10, L.MODERATE), (90, L.LOW)], duration=9000)
    assert order(a=a, b=b) == ["b", "a"]


def test_travel_time_is_the_last_tiebreaker():
    a = metrics([(100, L.LOW)], duration=5000)
    b = metrics([(100, L.LOW)], duration=4000)
    c = metrics([(100, L.LOW)], duration=6000)
    assert order(a=a, b=b, c=c) == ["b", "a", "c"]


def test_full_three_route_ordering():
    a = metrics([(100, L.LOW), (20, L.SEVERE)], duration=3000)
    b = metrics([(100, L.LOW), (5, L.SEVERE), (30, L.HIGH)], duration=4000)
    c = metrics([(100, L.LOW), (5, L.SEVERE), (10, L.HIGH)], duration=5000)
    assert order(a=a, b=b, c=c) == ["c", "b", "a"]


def test_float_noise_does_not_decide_the_ranking():
    a = metrics([(0.1 + 0.2, L.SEVERE), (100, L.LOW)], duration=1000)
    b = metrics([(0.3, L.SEVERE), (100, L.LOW)], duration=2000)
    assert order(a=a, b=b) == ["a", "b"]  # equal severe miles -> faster route wins


# --- No Travel gate ---------------------------------------------------------------------------
def test_route_with_no_travel_is_never_recommended_over_a_safe_alternative():
    unsafe_fast = metrics([(200, L.LOW), (1, L.NO_TRAVEL)], duration=100)
    safe_slow_severe = metrics([(100, L.SEVERE), (100, L.HIGH)], duration=99_999)
    assert order(a=unsafe_fast, b=safe_slow_severe) == ["b", "a"]


def test_among_unsafe_routes_fewest_no_travel_miles_first():
    a = metrics([(30, L.NO_TRAVEL), (70, L.LOW)])
    b = metrics([(5, L.NO_TRAVEL), (95, L.SEVERE)])
    assert order(a=a, b=b) == ["b", "a"]


def test_route_without_any_weather_is_not_rewarded():
    known = metrics([(100, L.MODERATE)], duration=9000)
    blind = metrics([(100, None)], duration=1000)
    assert order(a=blind, b=known) == ["b", "a"]


# --- explanation ------------------------------------------------------------------------------
def explain(**routes):
    return build_recommendation(rank_routes(routes), LABELS)


def test_explanation_cites_fewer_severe_miles_and_lower_exposure():
    rec = explain(
        a=metrics([(100, L.LOW), (40, L.SEVERE)], duration=3000),
        b=metrics([(140, L.LOW)], duration=4000),
    )
    assert rec.recommended == "b"
    assert rec.headline.startswith("Route B is recommended because it has fewer severe-weather miles")
    assert "0.0 mi vs 40.0 mi on Route A" in rec.headline
    assert "lower overall weather exposure" in rec.headline


def test_explanation_mentions_time_tradeoff():
    rec = explain(
        a=metrics([(100, L.LOW), (40, L.SEVERE)], duration=3000),
        b=metrics([(140, L.LOW)], duration=6600),
    )
    assert any("longer than Route A" in d for d in rec.details)


def test_explanation_when_only_time_differs():
    rec = explain(a=metrics([(100, L.LOW)], duration=5000), b=metrics([(100, L.LOW)], duration=4000))
    assert rec.recommended == "b" and "weather exposure is the same" in rec.headline


def test_explanation_flags_no_travel_alternatives():
    rec = explain(
        a=metrics([(50, L.NO_TRAVEL), (50, L.LOW)], duration=1000),
        b=metrics([(100, L.LOW)], duration=5000),
        c=metrics([(100, L.LOW)], duration=6000),
    )
    assert rec.recommended == "b" and not rec.all_routes_unsafe
    assert any("Route A" in d and "No Travel" in d and "unsafe" in d for d in rec.details)


def test_all_routes_unsafe_is_called_out():
    rec = explain(
        a=metrics([(10, L.NO_TRAVEL), (90, L.LOW)]),
        b=metrics([(40, L.NO_TRAVEL), (60, L.LOW)]),
    )
    assert rec.all_routes_unsafe and rec.recommended == "a"
    assert "still unsafe" in rec.headline
    assert any("Every route contains No Travel" in w for w in rec.warnings)


def test_explanation_handles_missing_weather_and_single_route():
    rec = explain(a=metrics([(100, None)]))
    assert "no weather data" in rec.headline and rec.warnings
    solo = explain(a=metrics([(100, L.LOW)]))
    assert "only route" in solo.headline


def test_partial_coverage_adds_warning():
    # Route A has only 60% weather coverage but is otherwise clean; it still wins on the known data.
    rec = explain(a=metrics([(60, L.LOW), (40, None)]), b=metrics([(100, L.HIGH)]))
    assert rec.recommended == "a"
    assert any("covers 60%" in w for w in rec.warnings)
