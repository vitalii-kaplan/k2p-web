from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.utils import timezone


def _static_text_response(path: str, content_type: str) -> HttpResponse:
    found = finders.find(path)
    if not found:
        return HttpResponse("not found\n", status=404, content_type="text/plain; charset=utf-8")

    with open(found, encoding="utf-8") as fp:
        body = fp.read()
    return HttpResponse(body, content_type=content_type)


def robots_txt(_request):
    return _static_text_response("robots.txt", "text/plain; charset=utf-8")


def sitemap_xml(_request):
    return _static_text_response("sitemap.xml", "application/xml; charset=utf-8")


def security_txt(_request):
    expires_at = timezone.now() + timedelta(days=getattr(settings, "SECURITY_TXT_EXPIRES_DAYS", 365))
    lines = []

    for contact in getattr(settings, "SECURITY_TXT_CONTACTS", []):
        lines.append(f"Contact: {contact}")

    canonical = getattr(settings, "SECURITY_TXT_CANONICAL", "")
    if canonical:
        lines.append(f"Canonical: {canonical}")

    preferred_languages = getattr(settings, "SECURITY_TXT_PREFERRED_LANGUAGES", "")
    if preferred_languages:
        lines.append(f"Preferred-Languages: {preferred_languages}")

    lines.append(f"Expires: {expires_at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}")

    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
