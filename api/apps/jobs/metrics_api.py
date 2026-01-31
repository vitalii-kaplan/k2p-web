from __future__ import annotations

import os
import sys

from django.conf import settings
from django.db.models import Count, Max
from prometheus_client import Counter, REGISTRY
from prometheus_client.core import GaugeMetricFamily

from .models import Job


JOB_CREATED_TOTAL = Counter(
    "k2p_job_created_total",
    "Total number of jobs created",
)

ENQUEUE_REJECTED_TOTAL = Counter(
    "k2p_enqueue_rejected_total",
    "Total number of job enqueue rejections",
)


class JobsDbMetricsCollector:
    def collect(self):
        counts = (
            Job.objects.values("status")
            .annotate(count=Count("id"))
            .iterator()
        )
        counts_by_status = {row["status"]: row["count"] for row in counts}

        jobs_by_state = GaugeMetricFamily(
            "k2p_jobs_by_state",
            "Number of jobs by state",
            labels=["state"],
        )
        for status in Job.Status:
            jobs_by_state.add_metric(
                [status.value],
                counts_by_status.get(status.value, 0),
            )
        yield jobs_by_state

        queue_depth = GaugeMetricFamily(
            "k2p_job_queue_depth",
            "Number of jobs in QUEUED state",
        )
        queue_depth.add_metric([], counts_by_status.get(Job.Status.QUEUED.value, 0))
        yield queue_depth

        last_finished = Job.objects.aggregate(latest=Max("finished_at"))["latest"]
        last_finished_ts = last_finished.timestamp() if last_finished else 0
        last_finished_metric = GaugeMetricFamily(
            "k2p_last_job_finished_timestamp_seconds",
            "Unix timestamp of most recently finished job",
        )
        last_finished_metric.add_metric([], last_finished_ts)
        yield last_finished_metric


_RUNNING_PYTEST = (
    settings.IS_PYTEST
    or "PYTEST_CURRENT_TEST" in os.environ
    or "pytest" in sys.modules
)

if not _RUNNING_PYTEST and not getattr(REGISTRY, "_k2p_jobs_db_collector_registered", False):
    REGISTRY.register(JobsDbMetricsCollector())
    setattr(REGISTRY, "_k2p_jobs_db_collector_registered", True)
