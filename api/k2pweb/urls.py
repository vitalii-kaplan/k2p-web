from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from rest_framework.schemas import get_schema_view
from rest_framework.permissions import AllowAny

from apps.core.admin_views import sql_console
from apps.core.health import healthz, readyz
from apps.core.views import robots_txt, security_txt, sitemap_xml
from django.conf import settings

urlpatterns = [
    path("", include("django_prometheus.urls")),
    # UI
    path("", TemplateView.as_view(template_name="ui/index.html"), name="ui-index"),
    path("robots.txt", robots_txt, name="robots-txt"),
    path("sitemap.xml", sitemap_xml, name="sitemap-xml"),
    path(".well-known/security.txt", security_txt, name="security-txt"),

    # Admin + health
    path("admin/sql/", sql_console, name="admin-sql-console"),
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),

    # API
    path("api/", include("apps.jobs.urls")),
]

if settings.DEBUG or getattr(settings, "EXPOSE_SCHEMA", False):
    urlpatterns.append(
        path(
            "api/schema/",
            get_schema_view(
                title="k2p-web API",
                version="1.0.0",
                permission_classes=[AllowAny],
            ),
            name="openapi-schema",
        )
    )
