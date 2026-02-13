from __future__ import annotations

import hashlib
import json
import logging
import zipfile
import xml.etree.ElementTree as ET
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from rest_framework import serializers

from .models import Job, JobSettingsMeta
from .metrics_api import JOB_CREATED_TOTAL
from .security import ZipLimits, ZipValidationError, validate_zipfile

logger = logging.getLogger("k2p.jobs")

class JobCreateSerializer(serializers.Serializer):
    bundle = serializers.FileField()

    def validate_bundle(self, f) -> Any:
        content_type = getattr(f, "content_type", "") or ""
        name = getattr(f, "name", "")
        if not name.lower().endswith(".zip"):
            raise serializers.ValidationError("Only .zip files are accepted.")
        allowed_types = {
            "",
            "application/zip",
            "application/x-zip-compressed",
            "multipart/x-zip",
            "application/octet-stream",
        }
        if content_type not in allowed_types:
            raise serializers.ValidationError("Invalid content type for zip upload.")
        return f

    @staticmethod
    def _safe_stem(filename: str) -> str:
        stem = Path(filename).stem or "workflow"
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
        return stem[:80] or "workflow"

    def create(self, validated_data: dict) -> Job:
        f = validated_data["bundle"]

        job = Job.objects.create(
            status=Job.Status.QUEUED,
            original_filename=getattr(f, "name", "")[:255],
            input_size=getattr(f, "size", 0) or 0,
        )
        max_upload = getattr(settings, "MAX_UPLOAD_BYTES", 50 * 1024 * 1024)
        if job.input_size and max_upload >= 0 and job.input_size > max_upload:
            job.status = Job.Status.FAILED
            job.error_code = "upload_too_large"
            job.error_message = f"Upload too large (max {max_upload} bytes)."
            job.save(update_fields=["status", "error_code", "error_message"])
            raise serializers.ValidationError(job.error_message, code="too_large")

        try:
            f.seek(0)
            with zipfile.ZipFile(f, "r") as zf:
                limits = ZipLimits(
                    max_files=getattr(settings, "MAX_ZIP_FILES", 2000),
                    max_path_depth=getattr(settings, "MAX_ZIP_PATH_DEPTH", 20),
                    max_unpacked_bytes=getattr(settings, "MAX_UNPACKED_BYTES", 300 * 1024 * 1024),
                    max_file_bytes=getattr(settings, "MAX_FILE_BYTES", 50 * 1024 * 1024),
                )
                names = validate_zipfile(zf, limits)
                names = [
                    n
                    for n in names
                    if not (n.startswith("__MACOSX/") or "/__MACOSX/" in n or Path(n).name.startswith("._"))
                ]
                has_root_workflow = any(n.lower() == "workflow.knime" for n in names)
                if not has_root_workflow:
                    raise ZipValidationError(
                        "missing_workflow_root",
                        "workflow.knime must be at the top level of the zip.",
                    )
        except ZipValidationError as exc:
            job.status = Job.Status.FAILED
            job.error_code = exc.code
            job.error_message = exc.message
            job.save(update_fields=["status", "error_code", "error_message"])
            raise serializers.ValidationError(exc.message, code=exc.code) from exc
        except zipfile.BadZipFile as exc:
            job.status = Job.Status.FAILED
            job.error_code = "invalid_zip"
            job.error_message = "Uploaded file is not a valid ZIP archive."
            job.save(update_fields=["status", "error_code", "error_message"])
            raise serializers.ValidationError(job.error_message) from exc
        finally:
            try:
                f.seek(0)
            except Exception:
                pass

        stem = self._safe_stem(getattr(f, "name", "bundle.zip"))
        # Store under JOB_STORAGE_ROOT/jobs/<uuid>/<stem>.zip (repo-local var/ for dev)
        rel_key = f"jobs/{job.id}/{stem}.zip"

        root = getattr(settings, "JOB_STORAGE_ROOT", None)
        if root is None:
            raise RuntimeError("JOB_STORAGE_ROOT is not configured in Django settings.")

        full_path = Path(root) / rel_key
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute sha256 while writing
        hasher = hashlib.sha256()
        with open(full_path, "wb") as dst:
            for chunk in f.chunks(chunk_size=1024 * 1024):
                hasher.update(chunk)
                dst.write(chunk)

        # Validate XML files inside the zip
        try:
            with zipfile.ZipFile(full_path, "r") as zf:
                limits = ZipLimits(
                    max_files=getattr(settings, "MAX_ZIP_FILES", 2000),
                    max_path_depth=getattr(settings, "MAX_ZIP_PATH_DEPTH", 20),
                    max_unpacked_bytes=getattr(settings, "MAX_UNPACKED_BYTES", 300 * 1024 * 1024),
                    max_file_bytes=getattr(settings, "MAX_FILE_BYTES", 50 * 1024 * 1024),
                )
                names = validate_zipfile(zf, limits)
                names = [
                    n
                    for n in names
                    if not (n.startswith("__MACOSX/") or "/__MACOSX/" in n or Path(n).name.startswith("._"))
                ]
                for name in names:
                    if name.startswith("__MACOSX/") or "/__MACOSX/" in name or Path(name).name.startswith("._"):
                        continue
                    if not name.lower().endswith(".xml") and not name.lower().endswith("workflow.knime"):
                        continue
                    try:
                        data = zf.read(name)
                        ET.fromstring(data)
                    except ET.ParseError as exc:
                        raise serializers.ValidationError(f"Invalid XML in {name}.") from exc
        except (zipfile.BadZipFile, serializers.ValidationError, ZipValidationError) as exc:
            # cleanup on invalid archive or XML
            full_path.unlink(missing_ok=True)
            job.status = Job.Status.FAILED
            if isinstance(exc, zipfile.BadZipFile):
                job.error_code = "invalid_zip"
                job.error_message = "Uploaded file is not a valid ZIP archive."
            elif isinstance(exc, ZipValidationError):
                job.error_code = exc.code
                job.error_message = exc.message
            else:
                job.error_code = "invalid_xml"
                job.error_message = str(exc)
            job.save(update_fields=["status", "error_code", "error_message"])
            if isinstance(exc, zipfile.BadZipFile):
                raise serializers.ValidationError(job.error_message) from exc
            if isinstance(exc, ZipValidationError):
                raise serializers.ValidationError(exc.message, code=exc.code) from exc
            raise serializers.ValidationError(job.error_message) from exc

        # Extract settings.xml metadata and store per-file rows.
        with zipfile.ZipFile(full_path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("__MACOSX/") or "/__MACOSX/" in name or Path(name).name.startswith("._"):
                    continue
                if not name.lower().endswith("settings.xml"):
                    continue
                factory = node_name = display_name = None
                try:
                    data = zf.read(name)
                    root = ET.fromstring(data)
                    for entry in root.iter():
                        if not entry.tag.endswith("entry"):
                            continue
                        key = entry.attrib.get("key")
                        if key == "factory":
                            factory = entry.attrib.get("value")
                        elif key == "node-name":
                            node_name = entry.attrib.get("value")
                        elif key == "name":
                            display_name = entry.attrib.get("value")
                except ET.ParseError:
                    # Invalid XML already validated above; skip metadata on parse error.
                    pass

                JobSettingsMeta.objects.create(
                    job=job,
                    file_name=name,
                    factory=factory,
                    node_name=node_name,
                    name=display_name,
                )

        job.input_key = rel_key  # storage key; not an absolute path
        job.input_sha256 = hasher.hexdigest()
        job.save(update_fields=["input_key", "input_sha256"])

        JOB_CREATED_TOTAL.inc()
        logger.info(
            json.dumps(
                {
                    "event": "job_created",
                    "job_id": str(job.id),
                    "input_size": job.input_size,
                    "input_sha256_prefix": (job.input_sha256 or "")[:12],
                }
            )
        )

        return job


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "id",
            "created_at",
            "started_at",
            "finished_at",
            "status",
            "original_filename",
            "input_size",
            "input_sha256",
            "input_key",
            "error_code",
            "error_message",
        ]
