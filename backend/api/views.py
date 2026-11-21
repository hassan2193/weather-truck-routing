"""Thin REST views: validate input, call the services, serialize output."""
from __future__ import annotations

from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from routing.forecast import build_route_forecast
from routing.geocoding import resolve_place, search_places
from routing.models import Analysis, Route
from routing.services import analyze_trip

from .serializers import (
    AnalysisSerializer,
    AnalyzeRequestSerializer,
    CheckpointSerializer,
    RouteSerializer,
)


class AnalyzeThrottle(AnonRateThrottle):
    """Analyses fan out to three external APIs, so they get a tighter limit."""

    scope = "analyze"
    rate = "30/hour"


class AnalyzeView(APIView):
    """POST /api/routes/analyze/ - generate, weather-score and rank three routes."""

    throttle_classes = [AnalyzeThrottle]

    def post(self, request):
        data = AnalyzeRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        analysis = analyze_trip(
            origin=resolve_place(v["origin"]),
            destination=resolve_place(v["destination"]),
            departure=v["departure_time"],
            load_lb=v["load_weight_lb"],
            interval_miles=v["interval_miles"],
        )
        analysis = Analysis.objects.prefetch_related("routes__checkpoints").get(pk=analysis.pk)
        return Response(AnalysisSerializer(analysis).data, status=status.HTTP_201_CREATED)


class AnalysisDetailView(APIView):
    """GET /api/analyses/{id}/ - reload a previous analysis."""

    def get(self, request, pk):
        analysis = get_object_or_404(Analysis.objects.prefetch_related("routes__checkpoints"), pk=pk)
        return Response(AnalysisSerializer(analysis).data)


class RouteDetailView(APIView):
    """GET /api/routes/{id}/ - one route with its metrics and geometry."""

    def get(self, request, pk):
        route = get_object_or_404(Route, pk=pk)
        return Response(RouteSerializer(route).data)


class RouteCheckpointsView(APIView):
    """GET /api/routes/{id}/checkpoints/ - weather checkpoints in travel order."""

    def get(self, request, pk):
        route = get_object_or_404(Route, pk=pk)
        checkpoints = route.checkpoints.all()
        return Response({"route_id": str(route.id), "count": len(checkpoints),
                         "checkpoints": CheckpointSerializer(checkpoints, many=True).data})


class RouteForecastView(APIView):
    """GET /api/routes/{id}/forecast/ - 0-48 h corridor forecast for the heatmap/slider."""

    def get(self, request, pk):
        route = get_object_or_404(Route.objects.select_related("analysis"), pk=pk)
        return Response(build_route_forecast(route))


@api_view(["GET"])
def geocode(request):
    """GET /api/geocode/?q=... - address autocomplete."""
    query = request.query_params.get("q", "")
    places = search_places(query, limit=5)
    return Response({"results": [p.to_dict() for p in places]})


@api_view(["GET"])
@throttle_classes([])
def health(request):
    """GET /api/health/ - liveness and configuration for the UI status indicator."""
    from django.conf import settings

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db = {"status": "ok", "engine": connection.vendor}
    except Exception as exc:  # noqa: BLE001 - report any DB failure as unhealthy
        db = {"status": "error", "engine": connection.vendor, "detail": str(exc)[:200]}
    return Response({
        "status": "ok" if db["status"] == "ok" else "degraded",
        "database": db,
        "providers": {
            "routing": {"name": "Valhalla (truck)", "url": settings.VALHALLA_URL},
            "weather": {"name": "Open-Meteo", "url": settings.OPEN_METEO_URL},
            "geocoding": {"name": "Photon / Nominatim (OpenStreetMap)"},
        },
    }, status=200 if db["status"] == "ok" else 503)
