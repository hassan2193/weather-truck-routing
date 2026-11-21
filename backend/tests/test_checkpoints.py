"""Checkpoint generation, geometry and ETA calculations."""
from datetime import UTC, datetime, timedelta

import pytest

from routing.checkpoints import (
    TimeProfile,
    checkpoint_distances,
    generate_checkpoints,
    segment_bounds,
)
from routing.geometry import (
    cumulative_miles,
    decode_polyline,
    encode_polyline,
    haversine_miles,
    point_at_distance,
)

DEP = datetime(2026, 12, 1, 8, 0, tzinfo=UTC)


def flat(points):
    return [v for p in points for v in p]


def straight_line(n=101, start=(40.0, -100.0), end=(40.0, -90.0)):
    return [(start[0] + (end[0] - start[0]) * i / (n - 1), start[1] + (end[1] - start[1]) * i / (n - 1)) for i in range(n)]


def test_polyline_roundtrip():
    pts = [(41.878123, -87.629812), (41.9, -87.7), (32.776272, -96.796856)]
    decoded = decode_polyline(encode_polyline(pts))
    assert flat(decoded) == pytest.approx(flat(pts), abs=1e-6)


def test_known_polyline_decodes():
    # Google's documented example (precision 5)
    decoded = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert flat(decoded) == pytest.approx(flat([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]), abs=1e-5)


def test_haversine_known_distance():
    assert haversine_miles((41.8781, -87.6298), (32.7767, -96.7970)) == pytest.approx(802, abs=3)


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_checkpoint_distances_include_origin_interval_steps_and_destination(interval):
    d = checkpoint_distances(137.0, interval)
    assert d[0] == 0 and d[-1] == 137.0
    assert d[1:-1] == [float(k * interval) for k in range(1, int(137 // interval) + 1)]
    assert d == sorted(set(d))


def test_checkpoint_distance_exact_multiple_has_no_duplicate_end():
    assert checkpoint_distances(100, 25) == [0, 25, 50, 75, 100]


def test_checkpoint_short_trip_has_origin_and_destination_only():
    assert checkpoint_distances(7.5, 25) == [0, 7.5]


@pytest.mark.parametrize("bad", [0, -5])
def test_invalid_interval(bad):
    with pytest.raises(ValueError):
        checkpoint_distances(100, bad)


@pytest.mark.parametrize("total,interval", [(137.0, 10), (137.0, 25), (137.0, 50), (100, 25), (7.5, 25), (1000.3, 10)])
def test_segments_tile_the_route_exactly(total, interval):
    dists = checkpoint_distances(total, interval)
    bounds = segment_bounds(dists)
    assert bounds[0][0] == 0 and bounds[-1][1] == total
    for (_, end), (start, _) in zip(bounds, bounds[1:]):
        assert end == pytest.approx(start)
    assert sum(e - s for s, e in bounds) == pytest.approx(total)


def test_checkpoints_lie_on_the_route_at_the_right_distance():
    line = straight_line()
    total = cumulative_miles(line)[-1]
    specs = generate_checkpoints(line, total, 25)
    assert specs[0].distance_mi == 0 and (specs[0].lat, specs[0].lon) == line[0]
    assert (specs[-1].lat, specs[-1].lon) == line[-1]
    for s in specs:
        assert haversine_miles(line[0], (s.lat, s.lon)) == pytest.approx(s.distance_mi, abs=0.6)
        assert s.lat == pytest.approx(40.0)  # stays on the line
    assert sum(s.segment_mi for s in specs) == pytest.approx(total)


def test_checkpoints_follow_a_bent_route_not_the_chord():
    bent = [(40.0, -100.0), (40.0, -95.0), (44.0, -95.0)]  # east then north
    total = cumulative_miles(bent)[-1]
    specs = generate_checkpoints(bent, total, 50)
    corner = cumulative_miles(bent)[1]
    after = [s for s in specs if s.distance_mi > corner + 5]
    assert after and all(s.lon == pytest.approx(-95.0, abs=1e-6) for s in after)
    assert all(s.lat > 40.0 for s in after)


def test_reported_road_distance_rescales_checkpoint_positions():
    line = straight_line()
    geo = cumulative_miles(line)[-1]
    specs = generate_checkpoints(line, geo * 1.1, 50)  # provider says the road is 10% longer
    assert specs[-1].distance_mi == pytest.approx(geo * 1.1)
    assert (specs[-1].lat, specs[-1].lon) == line[-1]


def test_point_at_distance_clamps():
    line = straight_line(3)
    cum = cumulative_miles(line)
    assert point_at_distance(line, cum, -5) == line[0]
    assert point_at_distance(line, cum, 1e9) == line[-1]


# --- ETA ---------------------------------------------------------------------------
def test_constant_speed_eta():
    tp = TimeProfile.constant_speed(120, 7200)  # 60 mph
    assert tp.eta(DEP, 0) == DEP
    assert tp.eta(DEP, 30) == DEP + timedelta(minutes=30)
    assert tp.eta(DEP, 120) == DEP + timedelta(hours=2)
    assert tp.eta(DEP, 500) == DEP + timedelta(hours=2)  # clamped


def test_eta_uses_varying_speed_profile():
    # 10 mi urban in 30 min (20 mph), then 100 mi highway in 1.5 h (~67 mph)
    tp = TimeProfile.from_segments([(10, 1800), (100, 5400)], 110, 7200)
    assert tp.eta(DEP, 10) == DEP + timedelta(minutes=30)
    assert tp.eta(DEP, 60) == DEP + timedelta(minutes=30 + 45)
    flat = TimeProfile.constant_speed(110, 7200)
    assert tp.elapsed_seconds(10) > flat.elapsed_seconds(10)  # slow start is reflected


def test_profile_rescales_to_reported_route_totals():
    tp = TimeProfile.from_segments([(50, 3000), (50, 3000)], total_miles=110, total_seconds=7200)
    assert tp.elapsed_seconds(110) == pytest.approx(7200)
    assert tp.elapsed_seconds(55) == pytest.approx(3600)


def test_profile_roundtrip_and_degenerate_segments():
    tp = TimeProfile.from_segments([(10, 600), (20, 600)], 30, 1200)
    assert TimeProfile.from_list(tp.to_list()).elapsed_seconds(15) == pytest.approx(tp.elapsed_seconds(15), abs=0.1)
    fallback = TimeProfile.from_segments([], 60, 3600)
    assert fallback.elapsed_seconds(30) == pytest.approx(1800)


def test_eta_is_monotonic_along_checkpoints():
    line = straight_line()
    total = cumulative_miles(line)[-1]
    tp = TimeProfile.from_segments([(total / 2, 3600), (total / 2, 1800)], total, 5400)
    etas = [tp.eta(DEP, s.distance_mi) for s in generate_checkpoints(line, total, 10)]
    assert etas == sorted(etas) and etas[0] == DEP
