from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from rest_framework.schemas import get_schema_view
from rest_framework.permissions import AllowAny

from apps.core.health import healthz
from apps.core.admin_views import sql_console

urlpatterns = [
    # UI
    path("", TemplateView.as_view(template_name="ui/index.html"), name="ui-index"),

    # Admin + health
    path("admin/sql/", sql_console, name="admin-sql-console"),
    path("admin/", admin.site.urls),
    path("healthz", healthz),

    # API
    path(
        "api/schema/",
        get_schema_view(
            title="k2p-web API",
            version="1.0.0",
            permission_classes=[AllowAny],
        ),
        name="openapi-schema",
    ),
    path("api/", include("apps.jobs.urls")),
]
