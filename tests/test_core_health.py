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
