"""Persistence for trip analyses: one Analysis -> up to 3 Routes -> many Checkpoints."""
from __future__ import annotations

import uuid

from django.db import models


class Analysis(models.Model):
    """One user request (origin, destination, departure, load) and its outcome."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    origin_label = models.CharField(max_length=300)
    origin_lat = models.FloatField()
    origin_lon = models.FloatField()
    destination_label = models.CharField(max_length=300)
    destination_lat = models.FloatField()
    destination_lon = models.FloatField()

    departure_time = models.DateTimeField()
    load_weight_lb = models.PositiveIntegerField()
    interval_miles = models.PositiveSmallIntegerField()

    recommendation = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    weather_stats = models.JSONField(default=dict)
    route_search = models.JSONField(default=dict, help_text="How the routes were found (direct vs diversified)")

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "analyses"

    def __str__(self) -> str:
        return f"{self.origin_label} -> {self.destination_label} ({self.departure_time:%Y-%m-%d %H:%M})"


class Route(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(Analysis, on_delete=models.CASCADE, related_name="routes")
    label = models.CharField(max_length=2)  # "A", "B", "C"
    index = models.PositiveSmallIntegerField()  # 0-based, ordered by travel time

    distance_mi = models.FloatField()
    duration_s = models.FloatField()
    arrival_time = models.DateTimeField()
    summary = models.CharField(max_length=300)
    has_toll = models.BooleanField(default=False)
    has_ferry = models.BooleanField(default=False)
    source = models.CharField(
        max_length=16, default="provider", help_text="provider = suggested directly; diversified = found by re-routing"
    )

    geometry = models.TextField(help_text="Encoded polyline (precision 6) of the route")
    time_profile = models.JSONField(help_text="[[distance_mi, elapsed_s], ...] used for ETAs")

    rank = models.PositiveSmallIntegerField(default=0)  # 1 = recommended
    is_recommended = models.BooleanField(default=False)
    metrics = models.JSONField(default=dict)
    no_travel = models.BooleanField(default=False)
    no_travel_reasons = models.JSONField(default=list)

    class Meta:
        ordering = ["analysis", "index"]
        constraints = [models.UniqueConstraint(fields=["analysis", "index"], name="uniq_route_index")]

    def __str__(self) -> str:
        return f"Route {self.label} ({self.distance_mi:.0f} mi)"


class Checkpoint(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="checkpoints")
    sequence = models.PositiveIntegerField()
    distance_mi = models.FloatField()
    segment_mi = models.FloatField()
    lat = models.FloatField()
    lon = models.FloatField()
    eta = models.DateTimeField()

    weather_status = models.CharField(max_length=32)  # see weather.series statuses
    valid_time = models.DateTimeField(null=True, blank=True)  # forecast slot used
    wind_mph = models.FloatField(null=True, blank=True)
    gust_mph = models.FloatField(null=True, blank=True)
    rain_in_hr = models.FloatField(null=True, blank=True)
    snow_in_hr = models.FloatField(null=True, blank=True)

    risk_level = models.SmallIntegerField(null=True, blank=True)  # risk_engine.RiskLevel value
    wind_level = models.SmallIntegerField(null=True, blank=True)
    rain_level = models.SmallIntegerField(null=True, blank=True)
    snow_level = models.SmallIntegerField(null=True, blank=True)
    load_rule = models.CharField(max_length=200, blank=True, default="")
    drivers = models.JSONField(default=list)

    class Meta:
        ordering = ["route", "sequence"]
        constraints = [models.UniqueConstraint(fields=["route", "sequence"], name="uniq_checkpoint_sequence")]

    def __str__(self) -> str:
        return f"Checkpoint {self.sequence} @ {self.distance_mi:.0f} mi"
