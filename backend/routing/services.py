"""Trip analysis pipeline: route -> checkpoints -> ETA -> weather -> risk -> recommendation.

This is the only module that wires the independent apps together; the REST
layer calls :func:`analyze_trip` and never contains business logic itself.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction

from config.http import Deadline
from recommendations.engine import rank_routes
from recommendations.explain import build_recommendation
from recommendations.metrics import RouteMetrics, Segment, compute_metrics
from risk_engine.levels import RiskLevel
from risk_engine.rules import RiskAssessment, assess
from weather.series import (
    BEYOND_HORIZON,
    NO_DATA,
    PROVIDER_ERROR,
    WeatherSample,
    sample_series,
)
from weather.service import WeatherLookup, get_series

from .checkpoints import CheckpointSpec, generate_checkpoints
from .errors import InvalidTrip
from .geocoding import Place
from .geometry import LatLon, encode_polyline, haversine_miles
from .models import Analysis, Checkpoint, Route
from .route_search import find_routes

logger = logging.getLogger(__name__)

ROUTE_LABELS = ("A", "B", "C")
MIN_TRIP_MILES = 0.5
MAX_REASON_GROUPS = 5


@dataclass
class _CheckpointResult:
    spec: CheckpointSpec
    eta: datetime
    sample: WeatherSample
    assessment: RiskAssessment | None


def evaluate_checkpoint(sample: WeatherSample, load_lb: float) -> RiskAssessment | None:
    """Risk for one checkpoint; ``None`` when no weather is available (never defaults to Low)."""
    if not sample.available:
        return None
    return assess(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, load_lb)


def no_travel_reasons(results: list[_CheckpointResult]) -> list[str]:
    """Group consecutive No Travel checkpoints into readable ranges with their drivers."""
    groups: list[list[_CheckpointResult]] = []
    for r in results:
        if r.assessment and r.assessment.level is RiskLevel.NO_TRAVEL:
            if groups and groups[-1][-1].spec.sequence == r.spec.sequence - 1:
                groups[-1].append(r)
            else:
                groups.append([r])
    lines = []
    for g in groups[:MAX_REASON_GROUPS]:
        first, last = g[0].spec, g[-1].spec
        if first is last:
            where = f"Mile {first.distance_mi:.0f}"
        else:
            where = f"Miles {first.distance_mi:.0f}-{last.distance_mi:.0f}"
        drivers = "; ".join(dict.fromkeys(d for r in g for d in r.assessment.drivers))  # type: ignore[union-attr]
        lines.append(f"{where}: {drivers}")
    if len(groups) > MAX_REASON_GROUPS:
        lines.append(f"...and {len(groups) - MAX_REASON_GROUPS} more No Travel stretches")
    return lines


def analyze_trip(
    origin: Place,
    destination: Place,
    departure: datetime,
    load_lb: int,
    interval_miles: int,
) -> Analysis:
    """Run the full pipeline and persist the result."""
    if haversine_miles((origin.lat, origin.lon), (destination.lat, destination.lon)) < MIN_TRIP_MILES:
        raise InvalidTrip("Origin and destination are too close together to route.")

    # Up to 3 genuinely distinct truck routes (direct alternates, then re-routing around them).
    deadline = Deadline(settings.ANALYSIS_DEADLINE_SECONDS)
    search = find_routes((origin.lat, origin.lon), (destination.lat, destination.lon), load_lb, deadline)
    provider_routes = sorted(search.routes, key=lambda r: r.duration_s)  # A is always the fastest
    route_message = search.explanation()

    warnings: list[str] = []
    if len(provider_routes) < 3 and route_message:
        warnings.append(route_message)

    # 1) Checkpoints + ETAs for every route.
    plans = []
    for route in provider_routes:
        specs = generate_checkpoints(route.geometry, route.distance_mi, interval_miles)
        etas = [route.time_profile.eta(departure, s.distance_mi) for s in specs]
        plans.append((route, specs, etas))

    # 2) One batched, de-duplicated, cached weather lookup for all checkpoints of all routes.
    points: list[LatLon] = [(s.lat, s.lon) for _, specs, _ in plans for s in specs]
    needed_until = max(etas[-1] for _, _, etas in plans) + timedelta(hours=1)
    # whatever is left of the budget (at least a few seconds) goes to the weather lookup
    lookup = get_series(points, needed_until, timeout=max(deadline.timeout(settings.HTTP_TIMEOUT_SECONDS), 5.0))

    # 3) Sample weather at each ETA and assess risk.
    cursor = 0
    route_results: list[list[_CheckpointResult]] = []
    for _, specs, etas in plans:
        results = []
        for spec, eta in zip(specs, etas):
            sample = sample_series(lookup.series[cursor], eta)
            results.append(_CheckpointResult(spec, eta, sample, evaluate_checkpoint(sample, load_lb)))
            cursor += 1
        route_results.append(results)

    # 4) Metrics + ranking + recommendation.
    labels = {str(i): f"Route {ROUTE_LABELS[i]}" for i in range(len(plans))}
    metrics: dict[str, RouteMetrics] = {}
    for i, ((route, _, _), results) in enumerate(zip(plans, route_results)):
        segments = [Segment(r.spec.segment_mi, r.assessment.level if r.assessment else None) for r in results]
        metrics[str(i)] = compute_metrics(segments, route.distance_mi, route.duration_s)
    ranking = rank_routes(metrics)
    recommendation = build_recommendation(ranking, labels)
    rank_of = {r.key: r.rank for r in ranking}

    warnings += _weather_warnings(route_results, lookup)

    with transaction.atomic():
        analysis = Analysis.objects.create(
            origin_label=origin.label, origin_lat=origin.lat, origin_lon=origin.lon,
            destination_label=destination.label, destination_lat=destination.lat, destination_lon=destination.lon,
            departure_time=departure, load_weight_lb=load_lb, interval_miles=interval_miles,
            recommendation={}, warnings=warnings,
            route_search={**search.to_dict(), "message": route_message},
            weather_stats={
                "unique_locations": lookup.unique_locations,
                "cache_hits": lookup.cache_hits,
                "upstream_requests": lookup.upstream_requests,
                "failed_locations": lookup.failed_locations,
                "checkpoints": len(points),
            },
        )
        recommended_id = None
        checkpoint_rows: list[Checkpoint] = []
        for i, ((route, _, _etas), results) in enumerate(zip(plans, route_results)):
            m = metrics[str(i)]
            reasons = no_travel_reasons(results)
            row = Route.objects.create(
                analysis=analysis, label=ROUTE_LABELS[i], index=i,
                distance_mi=route.distance_mi, duration_s=route.duration_s,
                arrival_time=route.time_profile.eta(departure, route.distance_mi),
                summary=route.summary, has_toll=route.has_toll, has_ferry=route.has_ferry, source=route.source,
                geometry=encode_polyline(route.geometry), time_profile=route.time_profile.to_list(),
                rank=rank_of[str(i)], is_recommended=rank_of[str(i)] == 1,
                metrics=metrics_to_dict(m), no_travel=m.has_no_travel, no_travel_reasons=reasons,
            )
            if row.is_recommended:
                recommended_id = str(row.id)
            checkpoint_rows += [_checkpoint_row(row, r) for r in results]
        Checkpoint.objects.bulk_create(checkpoint_rows, batch_size=500)
        analysis.recommendation = {
            "route_id": recommended_id,
            "route_label": ROUTE_LABELS[int(recommendation.recommended)],
            "headline": recommendation.headline,
            "details": recommendation.details,
            "warnings": recommendation.warnings,
            "all_routes_unsafe": recommendation.all_routes_unsafe,
        }
        analysis.save(update_fields=["recommendation"])
    logger.info(
        "Analysis %s: %d routes, %d checkpoints, %d unique weather cells (%d cache hits, %d upstream requests)",
        analysis.id, len(plans), len(points), lookup.unique_locations, lookup.cache_hits, lookup.upstream_requests,
    )
    return analysis


def metrics_to_dict(m: RouteMetrics) -> dict:
    return {
        "low_miles": round(m.low_miles, 2),
        "moderate_miles": round(m.moderate_miles, 2),
        "high_miles": round(m.high_miles, 2),
        "severe_miles": round(m.severe_miles, 2),
        "no_travel_miles": round(m.no_travel_miles, 2),
        "unknown_miles": round(m.unknown_miles, 2),
        "average_risk": None if m.average_risk is None else round(m.average_risk, 3),
        "weather_coverage": round(m.coverage, 4),
    }


def _checkpoint_row(route: Route, r: _CheckpointResult) -> Checkpoint:
    a, s = r.assessment, r.sample
    return Checkpoint(
        route=route, sequence=r.spec.sequence, distance_mi=r.spec.distance_mi, segment_mi=r.spec.segment_mi,
        lat=r.spec.lat, lon=r.spec.lon, eta=r.eta,
        weather_status=s.status, valid_time=s.valid_time,
        wind_mph=s.wind_mph, gust_mph=s.gust_mph, rain_in_hr=s.rain_in_hr, snow_in_hr=s.snow_in_hr,
        risk_level=int(a.level) if a else None,
        wind_level=int(a.wind_level) if a and a.wind_level is not None else None,
        rain_level=int(a.rain_level) if a and a.rain_level is not None else None,
        snow_level=int(a.snow_level) if a and a.snow_level is not None else None,
        load_rule=(a.load_rule or "") if a else "",
        drivers=list(a.drivers) if a else [],
    )


def _weather_warnings(route_results: list[list[_CheckpointResult]], lookup: WeatherLookup) -> list[str]:
    statuses = Counter(r.sample.status for results in route_results for r in results)
    total = sum(statuses.values())
    out = []
    if statuses[PROVIDER_ERROR]:
        out.append(
            f"Weather data could not be retrieved for {statuses[PROVIDER_ERROR]} of {total} checkpoints "
            "(weather service error). They are shown as unavailable and excluded from risk totals."
        )
    if statuses[BEYOND_HORIZON]:
        out.append(
            f"{statuses[BEYOND_HORIZON]} of {total} checkpoints arrive after the weather forecast horizon "
            "(16 days) and are shown as unavailable."
        )
    if statuses[NO_DATA]:
        out.append(f"The weather provider had no data for {statuses[NO_DATA]} checkpoint times.")
    return out
