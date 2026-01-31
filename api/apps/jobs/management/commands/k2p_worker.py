from __future__ import annotations

import json
import logging
import os
import time
from prometheus_client import start_http_server
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.db_logging import log_db_settings
from apps.jobs.k8s import (
    kubectl_apply_yaml,
    kubectl_get_job,
    job_state,
    normalize_job_name,
    render_job_manifest,
)
from apps.jobs.models import Job
from apps.jobs.metrics_worker import (
    JOB_DURATION_SECONDS,
    JOB_END_TO_END_SECONDS,
    JOB_FINISHED_TOTAL,
    JOB_QUEUE_WAIT_SECONDS,
    JOB_RUN_SECONDS,
    K2P_ERROR_TOTAL,
    K2P_EXIT_CODE_TOTAL,
    K8S_JOB_START_LATENCY_SECONDS,
    KUBECTL_FAILURES_TOTAL,
    WORKER_ERRORS_TOTAL,
    WORKER_HEARTBEAT_TIMESTAMP_SECONDS,
)

logger = logging.getLogger("k2p.worker")

class Command(BaseCommand):
    help = "Async dispatcher/reconciler: submits QUEUED jobs to k8s and updates RUNNING jobs."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0, help="Loop sleep seconds")

    def handle(self, *args, **opts):
        sleep_s = float(opts["sleep"])
        ns = getattr(settings, "K8S_NAMESPACE", "k2p")
        image = getattr(settings, "K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main")

        # Expose worker metrics
        addr = os.environ.get("WORKER_METRICS_ADDR", "0.0.0.0")
        port = int(os.environ.get("WORKER_METRICS_PORT", "8001"))
        start_http_server(port, addr=addr)
        log_db_settings(logger, event="worker_db_settings")

        try:
            while True:
                try:
                    self._submit_one(ns=ns, image=image)
                    self._reconcile_running(ns=ns)
                    WORKER_HEARTBEAT_TIMESTAMP_SECONDS.set(time.time())
                except Exception:  # noqa: BLE001
                    WORKER_ERRORS_TOTAL.inc()
                    raise
                time.sleep(sleep_s)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Worker stopped."))
            return

    def _submit_one(self, *, ns: str, image: str) -> None:
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(status=Job.Status.QUEUED)
                .order_by("created_at")
                .first()
            )
            if not job:
                return

            logger.info(
                json.dumps(
                    {
                        "event": "job_picked",
                        "job_id": str(job.id),
                    }
                )
            )

            job_name = normalize_job_name(str(job.id))
            job.k8s_namespace = ns
            job.k8s_job_name = job_name
            job.status = Job.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["k8s_namespace", "k8s_job_name", "status", "started_at"])

        if job.created_at and job.started_at:
            JOB_QUEUE_WAIT_SECONDS.observe((job.started_at - job.created_at).total_seconds())

        # Map repo paths into kind node mount (/repo/...)
        # input_key is e.g. jobs/<uuid>/<stem>.zip stored under JOB_STORAGE_ROOT
        in_host = Path(settings.JOB_STORAGE_ROOT) / job.input_key
        in_filename = Path(job.input_key).name or "bundle.zip"
        out_dir = Path(settings.RESULT_STORAGE_ROOT) / f"jobs/{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        manifest = render_job_manifest(
            namespace=ns,
            job_name=job.k8s_job_name,
            image=image,
            in_host_path=f"/repo/{in_host.relative_to(settings.REPO_ROOT)}",
            in_container_path=f"/in/{in_filename}",
            out_host_dir=f"/repo/{out_dir.relative_to(settings.REPO_ROOT)}",
        )

        submit_started = time.time()
        ok, _stdout, stderr = kubectl_apply_yaml(manifest)
        K8S_JOB_START_LATENCY_SECONDS.observe(time.time() - submit_started)
        if ok:
            logger.info(
                json.dumps(
                    {
                        "event": "k8s_job_created",
                        "job_id": str(job.id),
                        "k8s_job_name": job.k8s_job_name,
                        "k8s_namespace": job.k8s_namespace,
                    }
                )
            )
        if not ok:
            KUBECTL_FAILURES_TOTAL.inc()
            Job.objects.filter(id=job.id).update(
                status=Job.Status.FAILED,
                finished_at=timezone.now(),
                error_code="k8s_submit_failed",
                error_message=stderr[-4000:],
            )

    def _reconcile_running(self, *, ns: str) -> None:
        running = Job.objects.filter(status=Job.Status.RUNNING).exclude(k8s_job_name="")
        for j in running.iterator(chunk_size=50):
            job_json = kubectl_get_job(ns, j.k8s_job_name)
            if not job_json:
                continue

            state, exit_code = job_state(job_json)
            if state == "RUNNING":
                continue

            # For now: result_key points to the results directory
            result_key = f"jobs/{j.id}/"

            Job.objects.filter(id=j.id).update(
                status=Job.Status.SUCCEEDED if state == "SUCCEEDED" else Job.Status.FAILED,
                finished_at=timezone.now(),
                exit_code=exit_code,
                result_key=result_key,
                error_code="" if state == "SUCCEEDED" else "k8s_job_failed",
                error_message="" if state == "SUCCEEDED" else "Kubernetes Job failed (check cluster logs).",
            )
            finished_at = timezone.now()
            duration_s = None
            if j.started_at:
                duration_s = (finished_at - j.started_at).total_seconds()
                JOB_DURATION_SECONDS.observe(duration_s)
                JOB_RUN_SECONDS.observe(duration_s)
            if j.created_at:
                JOB_END_TO_END_SECONDS.observe((finished_at - j.created_at).total_seconds())
            JOB_FINISHED_TOTAL.labels(status=state).inc()
            if exit_code is not None:
                K2P_EXIT_CODE_TOTAL.labels(exit_code=str(exit_code)).inc()
            if state != "SUCCEEDED":
                K2P_ERROR_TOTAL.inc()
            logger.info(
                json.dumps(
                    {
                        "event": "job_finished",
                        "job_id": str(j.id),
                        "status": state,
                        "duration_seconds": duration_s,
                        "error_code": "" if state == "SUCCEEDED" else "k8s_job_failed",
                    }
                )
            )
