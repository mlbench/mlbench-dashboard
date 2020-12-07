from django.urls import include, path
from rest_framework import routers
from rest_framework.urlpatterns import format_suffix_patterns

from api import views

app_name = "api"

router = routers.DefaultRouter()
router.include_format_suffixes = False

router.register(r"pods", views.KubePodView, basename="pod")
router.register(r"runs", views.ModelRunView, basename="run")
router.register(r"metrics", views.KubeMetricsView, basename="metrics")

urlpatterns = [
    path(r"", include(router.urls)),
]

urlpatterns = format_suffix_patterns(urlpatterns, allowed=["json", "html", "zip"])
