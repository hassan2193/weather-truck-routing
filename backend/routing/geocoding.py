"""Geocoding: Photon (typeahead-friendly) with Nominatim as a fallback."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from config.http import get_session

from .errors import AddressNotFound, GeocodingError

logger = logging.getLogger(__name__)

CACHE_TTL = 24 * 3600
# Trucking app: restrict to North America, where the risk thresholds (mph, in/hr) apply.
NA_BBOX = "-170,15,-50,72"  # lon_min,lat_min,lon_max,lat_max (Photon bbox)


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return asdict(self)


def _photon_label(props: dict) -> str:
    parts = [props.get("name")]
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    if street and street != props.get("name"):
        parts.append(street)
    parts += [props.get("city") or props.get("county"), props.get("state"), props.get("country")]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return ", ".join(out)


def _photon(query: str, limit: int) -> list[Place]:
    resp = get_session().get(
        settings.PHOTON_URL,
        params={"q": query, "limit": limit, "lang": "en", "bbox": NA_BBOX},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    places = []
    for feat in resp.json().get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        places.append(Place(_photon_label(feat.get("properties", {})), lat, lon))
    return places


def _nominatim(query: str, limit: int) -> list[Place]:
    resp = get_session().get(
        settings.NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": limit, "countrycodes": "us,ca,mx"},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return [Place(r["display_name"], float(r["lat"]), float(r["lon"])) for r in resp.json()]


def search_places(query: str, limit: int = 5) -> list[Place]:
    """Return up to ``limit`` matching places. Raises GeocodingError if both providers fail."""
    query = " ".join(query.split())
    if len(query) < 2:
        return []
    key = "geo:" + hashlib.sha1(f"{limit}:{query.lower()}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    errors = []
    for provider in (_photon, _nominatim):
        try:
            places = provider(query, limit)
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning("Geocoder %s failed: %s", provider.__name__, exc)
            errors.append(exc)
            continue
        seen_labels: set[str] = set()
        places = [p for p in places if not (p.label in seen_labels or seen_labels.add(p.label))]
        if places:
            cache.set(key, places, CACHE_TTL)
            return places
    if len(errors) == 2:
        raise GeocodingError("The address search service is unavailable. Please try again.")
    return []


def resolve_place(value) -> Place:
    """Accept a ``Place``-like dict (already geocoded by autocomplete) or free text."""
    if isinstance(value, dict):
        return Place(str(value["label"]), float(value["lat"]), float(value["lon"]))
    places = search_places(str(value), limit=1)
    if not places:
        raise AddressNotFound(f"Could not find a location matching {str(value)!r}.")
    return places[0]
