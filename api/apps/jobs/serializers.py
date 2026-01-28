from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from rest_framework import serializers

from .models import Job


class JobCreateSerializer(serializers.Serializer):
    bundle = serializers.FileField()

    # hard limits for MVP
    max_size_bytes = 100 * 1024 * 1024  # 100 MiB

    def validate_bundle(self, f) -> Any:
        name = getattr(f, "name", "")
        if not name.lower().endswith(".zip"):
            raise serializers.ValidationError("Only .zip files are accepted.")
        size = getattr(f, "size", None)
        if size is not None and size > self.max_size_bytes:
            raise serializers.ValidationError(f"File too large (max {self.max_size_bytes} bytes).")
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

        job.input_key = rel_key  # storage key; not an absolute path
        job.input_sha256 = hasher.hexdigest()
        job.save(update_fields=["input_key", "input_sha256"])

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
