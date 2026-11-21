"""Settings for the automated tests (debug on, no real secrets needed)."""
import os

os.environ.setdefault("DJANGO_DEBUG", "true")

from .settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ["testserver", "localhost"]
LOGGING["root"]["level"] = "WARNING"  # noqa: F405

os.makedirs(STATIC_ROOT, exist_ok=True)  # noqa: F405 - silences WhiteNoise "no directory" warning
