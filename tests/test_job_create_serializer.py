from __future__ import annotations

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.jobs.serializers import JobCreateSerializer


class JobCreateSerializerTests(TestCase):
    def test_safe_stem_sanitizes_filename(self) -> None:
        safe = JobCreateSerializer._safe_stem("My Report (final)!!.ZIP")
        self.assertEqual(safe, "My_Report_final")

    def test_safe_stem_fallbacks(self) -> None:
        self.assertEqual(JobCreateSerializer._safe_stem(""), "workflow")
        self.assertEqual(JobCreateSerializer._safe_stem("..zip"), "workflow")

    def test_validate_bundle_rejects_non_zip(self) -> None:
        upload = SimpleUploadedFile("notes.txt", b"nope", content_type="text/plain")
        ser = JobCreateSerializer(data={"bundle": upload})
        self.assertFalse(ser.is_valid())
        self.assertIn("bundle", ser.errors)

    def test_validate_bundle_rejects_oversize(self) -> None:
        upload = SimpleUploadedFile("big.zip", b"xx", content_type="application/zip")
        ser = JobCreateSerializer(data={"bundle": upload})
        ser.max_size_bytes = 1
        self.assertFalse(ser.is_valid())
        self.assertIn("bundle", ser.errors)

    def test_create_uses_original_stem_in_input_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_data = b"zip-bytes"
            upload = SimpleUploadedFile("discounts.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                job = ser.save()

        self.assertTrue(job.input_key.startswith(f"jobs/{job.id}/"))
        self.assertTrue(job.input_key.endswith("/discounts.zip"))
