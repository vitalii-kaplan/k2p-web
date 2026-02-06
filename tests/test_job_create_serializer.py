from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import serializers

from apps.jobs.models import JobSettingsMeta
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
                    "CSV Reader (#1)/settings.xml": (
                        "<config>"
                        '<entry key="factory" type="xstring" value="org.knime.Factory"/>'
                        '<entry key="node-name" type="xstring" value="CSV Reader"/>'
                        '<entry key="name" type="xstring" value="CSV Reader"/>'
                        "</config>"
                    ),
                }
            )
            upload = SimpleUploadedFile("discounts.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                with patch("apps.jobs.serializers.logger") as logger:
                    job = ser.save()

        self.assertTrue(job.input_key.startswith(f"jobs/{job.id}/"))
        self.assertTrue(job.input_key.endswith("/discounts.zip"))
        meta = JobSettingsMeta.objects.get(job=job)
        self.assertEqual(meta.file_name, "CSV Reader (#1)/settings.xml")
        self.assertEqual(meta.factory, "org.knime.Factory")
        self.assertEqual(meta.node_name, "CSV Reader")
        self.assertEqual(meta.name, "CSV Reader")
        logger.info.assert_called()
        payload = logger.info.call_args[0][0]
        self.assertIn('"event": "job_created"', payload)

    def test_settings_meta_parsed_from_fixture(self) -> None:
        xml_text = (Path(__file__).resolve().parents[0] / "data" / "settings_meta" / "settings.xml").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            file_data = self._make_zip(
                {
                    "workflow.knime": "<root></root>",
                    "settings.xml": xml_text,
                }
            )
            upload = SimpleUploadedFile("meta.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                job = ser.save()

        meta = JobSettingsMeta.objects.get(job=job, file_name="settings.xml")
        self.assertEqual(meta.factory, "org.knime.base.node.meta.xvalidation.XValidatePartitionerFactory")
        self.assertEqual(meta.node_name, "X-Partitioner")
        self.assertEqual(meta.name, "X-Partitioner")

    def test_fixture_discounts_zip_is_valid_workflow(self) -> None:
        fixture = Path(__file__).resolve().parents[0] / "data" / "discounts.zip"
        file_data = fixture.read_bytes()
        upload = SimpleUploadedFile("discounts.zip", file_data, content_type="application/zip")

        ser = JobCreateSerializer(data={"bundle": upload})
        self.assertTrue(ser.is_valid(), ser.errors)

        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                job = ser.save()

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

    def test_create_rejects_missing_root_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_data = self._make_zip(
                {
                    "nested/workflow.knime": "<root></root>",
                    "nested/settings.xml": "<settings></settings>",
                }
            )
            upload = SimpleUploadedFile("nested.zip", file_data, content_type="application/zip")

            ser = JobCreateSerializer(data={"bundle": upload})
            self.assertTrue(ser.is_valid(), ser.errors)

            with override_settings(JOB_STORAGE_ROOT=tmpdir):
                with self.assertRaises(serializers.ValidationError) as exc:
                    ser.save()

        self.assertIn("workflow.knime must be at the top level", str(exc.exception))

    def _make_zip(self, files: dict[str, str]) -> bytes:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()
