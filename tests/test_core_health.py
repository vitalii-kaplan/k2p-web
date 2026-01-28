from __future__ import annotations

from django.test import Client, TestCase


class CoreHealthTests(TestCase):
    def test_healthz_returns_ok(self) -> None:
        client = Client()
        resp = client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
