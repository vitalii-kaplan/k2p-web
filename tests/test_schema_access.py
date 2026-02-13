import importlib

from django.test import TestCase, override_settings
from django.urls import clear_url_caches


def _reload_urls() -> None:
    clear_url_caches()
    import k2pweb.urls  # noqa: WPS433

    importlib.reload(k2pweb.urls)


class SchemaAccessTests(TestCase):
    def test_schema_hidden_by_default(self) -> None:
        _reload_urls()
        resp = self.client.get("/api/schema/")
        self.assertEqual(resp.status_code, 404)

    @override_settings(DEBUG=True, EXPOSE_SCHEMA=False)
    def test_schema_available_in_debug(self) -> None:
        _reload_urls()
        resp = self.client.get("/api/schema/")
        self.assertEqual(resp.status_code, 200)

    @override_settings(DEBUG=False, EXPOSE_SCHEMA=True)
    def test_schema_available_when_exposed(self) -> None:
        _reload_urls()
        resp = self.client.get("/api/schema/")
        self.assertEqual(resp.status_code, 200)
