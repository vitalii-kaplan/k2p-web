from __future__ import annotations

import io
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.jobs.models import Job


class NoCookieTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def _assert_no_set_cookie(self, resp) -> None:
        self.assertIsNone(resp.headers.get("Set-Cookie"))

    def test_get_root_no_set_cookie(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self._assert_no_set_cookie(resp)

    def test_post_jobs_no_set_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                upload = SimpleUploadedFile(
                    "discounts.zip",
                    self._make_zip(
                        {
                            "workflow.knime": "<root></root>",
                            "CSV Reader (#1)/settings.xml": "<settings></settings>",
                        }
                    ),
                    content_type="application/zip",
                )
                resp = self.client.post("/api/jobs", data={"bundle": upload}, format="multipart")

        self.assertEqual(resp.status_code, 201)
        self._assert_no_set_cookie(resp)

    def test_get_job_no_set_cookie(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED)
        resp = self.client.get(f"/api/jobs/{job.id}")
        self.assertEqual(resp.status_code, 200)
        self._assert_no_set_cookie(resp)

    def _make_zip(self, files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()
