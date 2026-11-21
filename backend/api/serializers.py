"""Request validation and response shapes."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from risk_engine.levels import RiskLevel
from routing.checkpoints import ALLOWED_INTERVALS
from routing.models import Analysis, Checkpoint, Route

MAX_LOAD_LB = 120_000


class PlaceField(serializers.Field):
    """A place is either free text or ``{"label", "lat", "lon"}`` from autocomplete."""

    default_error_messages = {"invalid": "Enter a location or choose one from the suggestions."}

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = " ".join(data.split())
            if len(text) < 2:
                self.fail("invalid")
            return text
        if isinstance(data, dict):
            try:
                lat, lon = float(data["lat"]), float(data["lon"])
                label = str(data.get("label") or f"{lat:.4f}, {lon:.4f}")[:300]
            except (KeyError, TypeError, ValueError):
                self.fail("invalid")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise serializers.ValidationError("Coordinates are out of range.")
            return {"label": label, "lat": lat, "lon": lon}
        self.fail("invalid")

    def to_representation(self, value):
        return value


class AnalyzeRequestSerializer(serializers.Serializer):
    origin = PlaceField()
    destination = PlaceField()
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=ALLOWED_INTERVALS, default=25)

    def validate_interval_miles(self, value):
        return int(value)

    def validate_departure_time(self, value):
        now = timezone.now()
        if value < now - timedelta(hours=1):
            raise serializers.ValidationError("Departure time cannot be in the past.")
        horizon = settings.WEATHER_MAX_FORECAST_DAYS
        if value > now + timedelta(days=horizon):
            raise serializers.ValidationError(
                f"Weather forecasts only extend {horizon} days ahead; choose an earlier departure."
            )
        return value


class CheckpointSerializer(serializers.ModelSerializer):
    weather = serializers.SerializerMethodField()
    risk = serializers.SerializerMethodField()

    class Meta:
        model = Checkpoint
        fields = ["sequence", "distance_mi", "segment_mi", "lat", "lon", "eta", "weather", "risk"]

    def get_weather(self, c: Checkpoint) -> dict:
        return {
            "status": c.weather_status,
            "valid_time": c.valid_time,
            "wind_mph": c.wind_mph,
            "gust_mph": c.gust_mph,
            "rain_in_hr": c.rain_in_hr,
            "snow_in_hr": c.snow_in_hr,
        }

    def get_risk(self, c: Checkpoint):
        if c.risk_level is None:
            return None

        def label(v):
            return None if v is None else RiskLevel(v).label

        return {
            "level": c.risk_level,
            "label": RiskLevel(c.risk_level).label,
            "wind": label(c.wind_level),
            "rain": label(c.rain_level),
            "snow": label(c.snow_level),
            "load_rule": c.load_rule or None,
            "drivers": c.drivers,
        }


class RouteSerializer(serializers.ModelSerializer):
    analysis_id = serializers.UUIDField(read_only=True)
    geometry_precision = serializers.SerializerMethodField()

    class Meta:
        model = Route
        fields = [
            "id", "analysis_id", "label", "index", "distance_mi", "duration_s", "arrival_time", "summary",
            "has_toll", "has_ferry", "source", "rank", "is_recommended", "no_travel", "no_travel_reasons", "metrics",
            "geometry", "geometry_precision",
        ]

    def get_geometry_precision(self, _route) -> int:
        return 6


class RouteWithCheckpointsSerializer(RouteSerializer):
    checkpoints = CheckpointSerializer(many=True, read_only=True)

    class Meta(RouteSerializer.Meta):
        fields = RouteSerializer.Meta.fields + ["checkpoints"]


class AnalysisSerializer(serializers.ModelSerializer):
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()
    routes = RouteWithCheckpointsSerializer(many=True, read_only=True)

    class Meta:
        model = Analysis
        fields = [
            "id", "created_at", "origin", "destination", "departure_time", "load_weight_lb", "interval_miles",
            "recommendation", "warnings", "weather_stats", "route_search", "routes",
        ]

    def get_origin(self, a: Analysis) -> dict:
        return {"label": a.origin_label, "lat": a.origin_lat, "lon": a.origin_lon}

    def get_destination(self, a: Analysis) -> dict:
        return {"label": a.destination_label, "lat": a.destination_lat, "lon": a.destination_lon}
