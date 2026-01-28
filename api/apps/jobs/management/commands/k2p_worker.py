from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.jobs.k8s import (
    kubectl_apply_yaml,
    kubectl_get_job,
    job_state,
    normalize_job_name,
    render_job_manifest,
)
from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Async dispatcher/reconciler: submits QUEUED jobs to k8s and updates RUNNING jobs."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0, help="Loop sleep seconds")

    def handle(self, *args, **opts):
        sleep_s = float(opts["sleep"])
        ns = getattr(settings, "K8S_NAMESPACE", "k2p")
        image = getattr(settings, "K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main")

        while True:
            self._submit_one(ns=ns, image=image)
            self._reconcile_running(ns=ns)
            time.sleep(sleep_s)

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

            job_name = normalize_job_name(str(job.id))
            job.k8s_namespace = ns
            job.k8s_job_name = job_name
            job.status = Job.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["k8s_namespace", "k8s_job_name", "status", "started_at"])

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

        ok, _stdout, stderr = kubectl_apply_yaml(manifest)
        if not ok:
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
