"""Django settings. All secrets and deployment-specific values come from the environment."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def database_from_url(url: str) -> dict:
    """Parse DATABASE_URL (postgres:// or sqlite:///) into a Django DATABASES entry."""
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql", "pgsql"}:
        options = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
            "OPTIONS": options,
        }
    if parsed.scheme == "sqlite":
        # sqlite:///relative.db, sqlite:////abs/path.db, or sqlite:///:memory:
        path = unquote(parsed.path)[1:]
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": path or ":memory:"}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "risk_engine",
    "routing",
    "weather",
    "recommendations",
    "api",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []  # no HTML templates; the React build is served as a static file

# PostgreSQL is the intended database (set DATABASE_URL). SQLite is only a
# zero-setup fallback for running the unit tests on a machine without Postgres.
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Static files / built frontend -----------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR / "frontend_dist"))
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.is_dir() else None
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- CORS -------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ALLOW_ALL_ORIGINS = False

# --- Security (production) --------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    # Platform health checks often arrive over plain HTTP; never redirect them.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))

# --- Django REST framework --------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "api.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_THROTTLE_RATE", "1000/hour")},
}

# --- Caching ----------------------------------------------------------------
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "wtr-cache"}}

# --- External providers -----------------------------------------------------
# Routing: Valhalla (truck costing, up to 2 alternates -> 3 routes). The public
# FOSSGIS instance needs no key but is rate-limited; point this at your own
# Valhalla or a commercial host for production traffic.
VALHALLA_URL = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de").rstrip("/")
VALHALLA_API_KEY = os.environ.get("VALHALLA_API_KEY", "")  # optional, sent as `api_key` if set
# Weather: Open-Meteo. A commercial key switches to the customer endpoint.
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
# Geocoding: Photon (typeahead) with Nominatim as fallback.
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io/api/")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
# Contact string for the User-Agent required by OSM-operated services.
HTTP_USER_AGENT = os.environ.get("HTTP_USER_AGENT", "weather-truck-routing/1.0")

HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "45"))
# Read timeout for one Valhalla request. Healthy responses take 1-6 s; a provider that is
# silent for 30 s is treated as unavailable rather than waited on.
ROUTING_TIMEOUT_SECONDS = float(os.environ.get("ROUTING_TIMEOUT_SECONDS", "30"))
# Whole-analysis budget (routing + re-routing + weather). Must stay below gunicorn's
# --timeout (120 s) and the frontend request timeout (120 s) so the user always gets an answer.
ANALYSIS_DEADLINE_SECONDS = float(os.environ.get("ANALYSIS_DEADLINE_SECONDS", "75"))
# Assumed empty weight of tractor + trailer, added to the load for route restrictions.
TRUCK_TARE_LB = int(os.environ.get("TRUCK_TARE_LB", "32000"))

# Weather sampling / caching
WEATHER_CACHE_TTL_SECONDS = int(os.environ.get("WEATHER_CACHE_TTL_SECONDS", "1800"))
WEATHER_GRID_DEGREES = float(os.environ.get("WEATHER_GRID_DEGREES", "0.05"))
WEATHER_BATCH_SIZE = int(os.environ.get("WEATHER_BATCH_SIZE", "50"))
WEATHER_MAX_FORECAST_DAYS = 16  # Open-Meteo forecast horizon

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
