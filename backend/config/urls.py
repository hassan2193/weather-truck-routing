from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path


def api_not_found(request):
    return JsonResponse({"error": {"code": "not_found", "message": "Unknown API endpoint.", "details": {}}}, status=404)


urlpatterns = [
    path("api/", include("api.urls")),
    re_path(r"^api/.*$", api_not_found),  # unknown API paths get JSON, never the SPA or an HTML page
]


def spa_index(request, _path=""):
    """Serve the built React app (single-service deployment). WhiteNoise serves its assets."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise Http404("Frontend build not found. Run `npm run build` or use the Vite dev server.")
    return FileResponse(open(index, "rb"), content_type="text/html")


if settings.FRONTEND_DIST.is_dir():
    urlpatterns.append(re_path(r"^(?!api/)(?P<_path>.*)$", spa_index))
