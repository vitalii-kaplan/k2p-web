from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import Client, TestCase, override_settings


class CoreHealthTests(TestCase):
    def test_healthz_returns_ok(self) -> None:
        client = Client()
        resp = client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_readyz_returns_ok(self) -> None:
        client = Client()
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = Path(tmpdir) / "jobs"
            results = Path(tmpdir) / "results"
            with override_settings(JOB_STORAGE_ROOT=str(jobs), RESULT_STORAGE_ROOT=str(results), EXPOSE_READYZ=True):
                resp = client.get("/readyz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["checks"]["db"], "ok")
        self.assertEqual(data["checks"]["job_storage_root"], "ok")
        self.assertEqual(data["checks"]["result_storage_root"], "ok")

    def test_readyz_fails_when_storage_unwritable(self) -> None:
        client = Client()
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_dir = Path(tmpdir) / "bad"
            bad_dir.mkdir(parents=True, exist_ok=True)
            bad_dir.chmod(0o400)
            try:
                with override_settings(JOB_STORAGE_ROOT=str(bad_dir), RESULT_STORAGE_ROOT=str(bad_dir), EXPOSE_READYZ=True):
                    resp = client.get("/readyz")
            finally:
                bad_dir.chmod(0o700)
        self.assertEqual(resp.status_code, 503)
        data = resp.json()
        self.assertEqual(data["status"], "fail")

    def test_readyz_hidden_in_prod(self) -> None:
        client = Client()
        with override_settings(DEBUG=False, EXPOSE_READYZ=False):
            resp = client.get("/readyz")
        self.assertEqual(resp.status_code, 404)

    def test_meta_handlers_csv_route_is_not_public(self) -> None:
        client = Client()
        resp = client.get("/meta/handlers.csv")
        self.assertEqual(resp.status_code, 404)


class PublicMetadataTests(TestCase):
    def test_security_txt_is_served_at_well_known_path(self) -> None:
        client = Client()
        with override_settings(
            SECURITY_TXT_CONTACTS=["mailto:vulnerability@example.com"],
            SECURITY_TXT_CANONICAL="https://k2pweb.org/.well-known/security.txt",
            SECURITY_TXT_PREFERRED_LANGUAGES="en",
        ):
            resp = client.get("/.well-known/security.txt")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Type"], "text/plain; charset=utf-8")
        body = resp.content.decode()
        self.assertIn("Contact: mailto:vulnerability@example.com\n", body)
        self.assertIn("Canonical: https://k2pweb.org/.well-known/security.txt\n", body)
        self.assertIn("Preferred-Languages: en\n", body)
        self.assertIn("Expires: ", body)

    def test_robots_txt_blocks_ai_crawlers_and_protects_private_paths(self) -> None:
        client = Client()
        resp = client.get("/robots.txt")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Type"], "text/plain; charset=utf-8")
        body = resp.content.decode()
        self.assertIn("User-agent: GPTBot\nDisallow: /\n", body)
        self.assertIn("User-agent: Google-Extended\nDisallow: /\n", body)
        self.assertIn("Disallow: /admin/\n", body)
        self.assertIn("Disallow: /api/\n", body)

    def test_sitemap_xml_is_served_at_root(self) -> None:
        client = Client()
        resp = client.get("/sitemap.xml")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Type"], "application/xml; charset=utf-8")
        self.assertIn("<loc>https://k2pweb.org/</loc>", resp.content.decode())
