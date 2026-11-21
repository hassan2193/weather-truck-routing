"""Exceptions raised by the routing and geocoding integrations."""


class RoutingError(Exception):
    """Base class for routing/geocoding failures."""


class NoRouteFound(RoutingError):
    """The provider could not connect the origin and destination."""


class RoutingProviderError(RoutingError):
    """The provider is unreachable, rate limiting us, or returned garbage."""


class GeocodingError(RoutingError):
    """Address lookup failed or found nothing."""


class AddressNotFound(GeocodingError):
    """The text did not match any known place."""


class InvalidTrip(RoutingError):
    """The requested trip cannot be analysed (for example origin equals destination)."""
