"""Uniform error responses: ``{"error": {"code", "message", "details"}}``."""
from __future__ import annotations

import logging

from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from routing.errors import AddressNotFound, GeocodingError, InvalidTrip, NoRouteFound, RoutingProviderError
from weather.open_meteo import WeatherProviderError

logger = logging.getLogger(__name__)

_DOMAIN_ERRORS = (
    (AddressNotFound, "address_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY),
    (InvalidTrip, "invalid_trip", status.HTTP_422_UNPROCESSABLE_ENTITY),
    (NoRouteFound, "no_route", status.HTTP_422_UNPROCESSABLE_ENTITY),
    (GeocodingError, "geocoding_unavailable", status.HTTP_502_BAD_GATEWAY),
    (RoutingProviderError, "routing_unavailable", status.HTTP_502_BAD_GATEWAY),
    (WeatherProviderError, "weather_unavailable", status.HTTP_502_BAD_GATEWAY),
)


def error_response(code: str, message: str, http_status: int, details=None) -> Response:
    return Response({"error": {"code": code, "message": message, "details": details or {}}}, status=http_status)


def exception_handler(exc, context):
    for exc_type, code, http_status in _DOMAIN_ERRORS:
        if isinstance(exc, exc_type):
            logger.warning("%s %s -> %s %s: %s", context["request"].method, context["request"].path,
                           http_status, code, exc)
            return error_response(code, str(exc), http_status)

    if isinstance(exc, ValidationError):
        return error_response("validation_error", "Please correct the highlighted fields.", 400, exc.detail)
    if isinstance(exc, Http404):
        return error_response("not_found", "The requested resource was not found.", 404)

    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        return error_response("request_error", str(detail or "Request failed."), response.status_code)

    logger.exception("Unhandled error in %s", context.get("view"))
    return error_response("internal_error", "Something went wrong on our side. Please try again.", 500)
