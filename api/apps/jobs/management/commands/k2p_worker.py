from __future__ import annotations

import json
import logging
import os
import time
import zipfile
import shutil
from pathlib import Path

from prometheus_client import start_http_server

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.db_logging import log_db_settings
from apps.jobs.models import Job
from apps.jobs.metrics_worker import (
    JOB_DURATION_SECONDS,
    JOB_END_TO_END_SECONDS,
    JOB_FINISHED_TOTAL,
    JOB_QUEUE_WAIT_SECONDS,
    JOB_RUN_SECONDS,
    K2P_ERROR_TOTAL,
    K2P_EXIT_CODE_TOTAL,
    WORKER_ERRORS_TOTAL,
    WORKER_HEARTBEAT_TIMESTAMP_SECONDS,
)
from apps.jobs.runner import DockerRunner, RunnerError
from apps.jobs.security import ZipLimits, ZipValidationError, safe_extract_zip

logger = logging.getLogger("k2p.worker")

class Command(BaseCommand):
    help = "Async dispatcher: runs QUEUED jobs via local runner and updates DB state."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0, help="Loop sleep seconds")

    def handle(self, *args, **opts):
        sleep_s = float(opts["sleep"])
        runner = self._build_runner()

        # Expose worker metrics
        addr = os.environ.get("WORKER_METRICS_ADDR", "0.0.0.0")
        port = int(os.environ.get("WORKER_METRICS_PORT", "8001"))
        start_http_server(port, addr=addr)
        log_db_settings(logger, event="worker_db_settings")

        try:
            while True:
                try:
                    self._run_one(runner=runner)
                    WORKER_HEARTBEAT_TIMESTAMP_SECONDS.set(time.time())
                except Exception:  # noqa: BLE001
                    WORKER_ERRORS_TOTAL.inc()
                    raise
                time.sleep(sleep_s)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Worker stopped."))
            return

    def _build_runner(self) -> DockerRunner:
        backend = getattr(settings, "JOB_RUNNER_BACKEND", "docker")
        if backend != "docker":
            raise RuntimeError(f"Unsupported JOB_RUNNER_BACKEND: {backend}")
        return DockerRunner(
            docker_bin=getattr(settings, "DOCKER_BIN", "docker"),
            image=getattr(settings, "K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main"),
            timeout_s=int(getattr(settings, "JOB_TIMEOUT_SECS", getattr(settings, "K2P_TIMEOUT_SECS", 300))),
            cpu=str(getattr(settings, "K2P_CPU", "1.0")),
            memory=str(getattr(settings, "K2P_MEMORY", "1g")),
            pids_limit=str(getattr(settings, "K2P_PIDS_LIMIT", "256")),
            command=str(getattr(settings, "K2P_COMMAND", "")) or None,
            args_template=str(getattr(settings, "K2P_ARGS_TEMPLATE", "")) or None,
            container_repo_root=Path(getattr(settings, "REPO_ROOT", ".")),
            container_job_storage_root=Path(getattr(settings, "JOB_STORAGE_ROOT", ".")),
            container_result_storage_root=Path(getattr(settings, "RESULT_STORAGE_ROOT", ".")),
            host_repo_root=str(getattr(settings, "HOST_REPO_ROOT", "")),
            host_job_storage_root=str(getattr(settings, "HOST_JOB_STORAGE_ROOT", "")),
            host_result_storage_root=str(getattr(settings, "HOST_RESULT_STORAGE_ROOT", "")),
            logger=logger,
        )

    def _run_one(self, *, runner: DockerRunner) -> None:
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

            job.status = Job.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["status", "started_at"])

        if job.created_at and job.started_at:
            JOB_QUEUE_WAIT_SECONDS.observe((job.started_at - job.created_at).total_seconds())

        # input_key is e.g. jobs/<uuid>/<stem>.zip stored under JOB_STORAGE_ROOT
        in_host = Path(settings.JOB_STORAGE_ROOT) / job.input_key
        out_dir = Path(settings.RESULT_STORAGE_ROOT) / f"jobs/{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        if not in_host.exists():
            Job.objects.filter(id=job.id).update(
                status=Job.Status.FAILED,
                finished_at=timezone.now(),
                error_code="input_missing",
                error_message=f"input file not found: {in_host}",
            )
            return

        # Unzip workflow into a working directory for runner.
        work_dir = out_dir / "_work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            limits = ZipLimits(
                max_files=getattr(settings, "MAX_ZIP_FILES", 2000),
                max_path_depth=getattr(settings, "MAX_ZIP_PATH_DEPTH", 20),
                max_unpacked_bytes=getattr(settings, "MAX_UNPACKED_BYTES", 300 * 1024 * 1024),
                max_file_bytes=getattr(settings, "MAX_FILE_BYTES", 50 * 1024 * 1024),
            )
            safe_extract_zip(in_host, work_dir, limits=limits)
        except zipfile.BadZipFile:
            Job.objects.filter(id=job.id).update(
                status=Job.Status.FAILED,
                finished_at=timezone.now(),
                error_code="invalid_zip",
                error_message="input zip is invalid",
            )
            return
        except ZipValidationError as exc:
            Job.objects.filter(id=job.id).update(
                status=Job.Status.FAILED,
                finished_at=timezone.now(),
                error_code=exc.code,
                error_message=exc.message,
            )
            return

        workflow_dir = work_dir
        found = list(work_dir.rglob("workflow.knime"))
        if found:
            workflow_dir = found[0].parent

        finished_at = timezone.now()
        exit_code: int | None = None
        stdout_tail = ""
        stderr_tail = ""
        status = Job.Status.SUCCEEDED
        error_code = ""
        error_message = ""

        try:
            result = runner.run_job(str(job.id), workflow_dir, out_dir)
            exit_code = result.get("exit_code")
            stdout_tail = result.get("stdout_tail", "") or ""
            stderr_tail = result.get("stderr_tail", "") or ""
            status = Job.Status.SUCCEEDED
            logger.info(
                json.dumps(
                    {
                        "event": "runner_job_finished",
                        "job_id": str(job.id),
                        "status": "SUCCEEDED",
                    }
                )
            )
        except RunnerError as exc:
            status = Job.Status.FAILED
            error_code = "runner_failed"
            exit_code = exc.exit_code
            stdout_tail = exc.stdout_tail
            stderr_tail = exc.stderr_tail
            msg = str(exc)
            detail = f"{msg}" if msg else "runner_failed"
            error_message = (
                f"runner_failed: {detail} "
                f"(exit={exc.exit_code}, stderr_tail={exc.stderr_tail[:1000]}, stdout_tail={exc.stdout_tail[:1000]})"
            )

        result_key = f"jobs/{job.id}/"
        finished_at = timezone.now()
        Job.objects.filter(id=job.id).update(
            status=status,
            finished_at=finished_at,
            exit_code=exit_code,
            result_key=result_key,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            error_code=error_code,
            error_message=error_message,
        )

        duration_s = None
        if job.started_at:
            duration_s = (finished_at - job.started_at).total_seconds()
            JOB_DURATION_SECONDS.observe(duration_s)
            JOB_RUN_SECONDS.observe(duration_s)
        if job.created_at:
            JOB_END_TO_END_SECONDS.observe((finished_at - job.created_at).total_seconds())

        JOB_FINISHED_TOTAL.labels(status=status.value).inc()
        if exit_code is not None:
            K2P_EXIT_CODE_TOTAL.labels(exit_code=str(exit_code)).inc()
        if status != Job.Status.SUCCEEDED:
            K2P_ERROR_TOTAL.inc()

        logger.info(
            json.dumps(
                {
                    "event": "job_finished",
                    "job_id": str(job.id),
                    "status": status.value,
                    "duration_seconds": duration_s,
                    "error_code": error_code,
                }
            )
        )
