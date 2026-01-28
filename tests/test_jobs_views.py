from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.jobs.models import Job


class JobsViewsTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_create_job_rejects_invalid_input(self) -> None:
        upload = SimpleUploadedFile("notes.txt", b"nope", content_type="text/plain")
        resp = self.client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "invalid_request")

    def test_create_and_get_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                upload = SimpleUploadedFile("discounts.zip", b"zip-bytes", content_type="application/zip")
                resp = self.client.post("/api/jobs", data={"bundle": upload}, format="multipart")

        self.assertEqual(resp.status_code, 201)
        job_id = resp.data["id"]

        detail = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["id"], job_id)
        self.assertEqual(detail.data["status"], Job.Status.QUEUED)

    def test_result_zip_requires_success(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED)
        resp = self.client.get(f"/api/jobs/{job.id}/result.zip")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["error"]["code"], "job_not_ready")

    def test_result_zip_missing_results_dir(self) -> None:
        job = Job.objects.create(status=Job.Status.SUCCEEDED)
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(RESULT_STORAGE_ROOT=tmpdir):
                resp = self.client.get(f"/api/jobs/{job.id}/result.zip")

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["error"]["code"], "missing_results")

    def test_result_zip_invalid_result_path(self) -> None:
        job = Job.objects.create(status=Job.Status.SUCCEEDED, result_key="../outside")
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(RESULT_STORAGE_ROOT=tmpdir):
                resp = self.client.get(f"/api/jobs/{job.id}/result.zip")

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["error"]["code"], "general_failure")

    def test_result_zip_streams_zip(self) -> None:
        job = Job.objects.create(status=Job.Status.SUCCEEDED)
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / f"jobs/{job.id}"
            results_dir.mkdir(parents=True, exist_ok=True)
            (results_dir / "out.txt").write_text("ok", encoding="utf-8")

            with override_settings(RESULT_STORAGE_ROOT=tmpdir):
                resp = self.client.get(f"/api/jobs/{job.id}/result.zip")

        self.assertEqual(resp.status_code, 200)
        data = b"".join(resp.streaming_content)
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            self.assertIn("out.txt", zf.namelist())
