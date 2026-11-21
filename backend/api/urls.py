from django.urls import path

from . import views

urlpatterns = [
    path("routes/analyze/", views.AnalyzeView.as_view(), name="analyze"),
    path("routes/<uuid:pk>/", views.RouteDetailView.as_view(), name="route-detail"),
    path("routes/<uuid:pk>/checkpoints/", views.RouteCheckpointsView.as_view(), name="route-checkpoints"),
    path("routes/<uuid:pk>/forecast/", views.RouteForecastView.as_view(), name="route-forecast"),
    path("analyses/<uuid:pk>/", views.AnalysisDetailView.as_view(), name="analysis-detail"),
    path("geocode/", views.geocode, name="geocode"),
    path("health/", views.health, name="health"),
]
