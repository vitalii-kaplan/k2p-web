from __future__ import annotations

import uuid
from django.db import models


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)

    original_filename = models.CharField(max_length=255, blank=True)
    input_size = models.BigIntegerField(default=0)
    input_sha256 = models.CharField(max_length=64, blank=True)

    k8s_namespace = models.CharField(max_length=64, default="k2p")
    k8s_job_name = models.CharField(max_length=128, blank=True)

    result_key = models.CharField(max_length=512, blank=True)  # e.g. results/<uuid>/
    exit_code = models.IntegerField(null=True, blank=True)

    stdout_tail = models.TextField(blank=True)
    stderr_tail = models.TextField(blank=True)

    # For now: local filesystem key under MEDIA_ROOT (later: S3 key)
    input_key = models.CharField(max_length=512, blank=True)

    # Error contract (filled later when k8s job fails)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.id} [{self.status}]"
