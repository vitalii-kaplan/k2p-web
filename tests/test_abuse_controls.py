from __future__ import annotations

from io import BytesIO
import zipfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.jobs.models import Job


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class AbuseControlTests(TestCase):
    def test_queue_full_rejects(self) -> None:
        client = APIClient()
        file_data = _make_zip({"workflow.knime": b"<root></root>"})
        upload = SimpleUploadedFile("test.zip", file_data, content_type="application/zip")
        with override_settings(MAX_QUEUED_JOBS=0):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 429)
        payload = resp.json()
        self.assertEqual(payload["error"]["code"], "queue_full")
        self.assertIn("counted_statuses", payload["error"]["details"])

    def test_upload_too_large_returns_413(self) -> None:
        client = APIClient()
        file_data = _make_zip({"workflow.knime": b"x" * 1024})
        upload = SimpleUploadedFile("big.zip", file_data, content_type="application/zip")
        with override_settings(MAX_UPLOAD_BYTES=10):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 413)

    def test_too_many_files_rejected(self) -> None:
        client = APIClient()
        file_data = _make_zip(
            {
                "workflow.knime": b"<root></root>",
                "a.xml": b"<a></a>",
            }
        )
        upload = SimpleUploadedFile("many.zip", file_data, content_type="application/zip")
        with override_settings(MAX_ZIP_FILES=1):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_zip_bomb_rejected(self) -> None:
        client = APIClient()
        file_data = _make_zip({"workflow.knime": b"x" * 50})
        upload = SimpleUploadedFile("bomb.zip", file_data, content_type="application/zip")
        with override_settings(MAX_UNPACKED_BYTES=10):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_path_traversal_rejected(self) -> None:
        client = APIClient()
        file_data = _make_zip(
            {
                "workflow.knime": b"<root></root>",
                "../evil.txt": b"nope",
            }
        )
        upload = SimpleUploadedFile("evil.zip", file_data, content_type="application/zip")
        resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_zip_marks_job_failed(self) -> None:
        client = APIClient()
        upload = SimpleUploadedFile("bad.zip", b"not a zip", content_type="application/zip")
        resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Job.objects.count(), 1)
        job = Job.objects.first()
        self.assertEqual(job.status, Job.Status.FAILED)

    def test_queue_counts_running(self) -> None:
        Job.objects.create(status=Job.Status.RUNNING)
        client = APIClient()
        file_data = _make_zip({"workflow.knime": b"<root></root>"})
        upload = SimpleUploadedFile("test.zip", file_data, content_type="application/zip")
        with override_settings(MAX_QUEUED_JOBS=1):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 429)

    def test_zip_encrypted_rejected(self) -> None:
        client = APIClient()
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            info = zipfile.ZipInfo("workflow.knime")
            info.flag_bits |= 0x1
            zf.writestr(info, b"<root></root>")
        upload = SimpleUploadedFile("enc.zip", buf.getvalue(), content_type="application/zip")
        encrypted = zipfile.ZipInfo("workflow.knime")
        encrypted.flag_bits |= 0x1
        encrypted.file_size = 1
        with patch("apps.jobs.security.zipfile.ZipFile.infolist", return_value=[encrypted]):
            resp = client.post("/api/jobs", data={"bundle": upload}, format="multipart")
        self.assertEqual(resp.status_code, 400)
