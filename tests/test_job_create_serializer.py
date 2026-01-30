from __future__ import annotations

import tempfile
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import serializers

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
            file_data = self._make_zip(
                {
                    "workflow.knime": "<root></root>",
                    "CSV Reader (#1)/settings.xml": "<settings></settings>",
                }
            )
            upload = SimpleUploadedFile("discounts.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                job = ser.save()

        self.assertTrue(job.input_key.startswith(f"jobs/{job.id}/"))
        self.assertTrue(job.input_key.endswith("/discounts.zip"))

    def test_create_rejects_invalid_xml_in_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_data = self._make_zip(
                {
                    "workflow.knime": "<root>",
                    "CSV Reader (#1)/settings.xml": "<settings></settings>",
                }
            )
            upload = SimpleUploadedFile("bad.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                with self.assertRaises(serializers.ValidationError):
                    ser.save()

    def _make_zip(self, files: dict[str, str]) -> bytes:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()
