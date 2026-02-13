from __future__ import annotations

import uuid
from pathlib import Path
import zipfile
import shutil

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.jobs.runner import DockerRunner, RunnerError
from apps.jobs.security import ZipLimits, ZipValidationError, safe_extract_zip


class Command(BaseCommand):
    help = "Run knime2py once via DockerRunner for a given workflow zip."

    def add_arguments(self, parser) -> None:
        parser.add_argument("zip_path", type=str, help="Path to workflow zip")

    def handle(self, *args, **opts) -> None:
        zip_path = Path(opts["zip_path"]).expanduser().resolve()
        if not zip_path.exists():
            raise SystemExit(f"Input zip not found: {zip_path}")

        out_dir = Path(settings.RESULT_STORAGE_ROOT) / "tmp-test" / str(uuid.uuid4())
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
            safe_extract_zip(zip_path, work_dir, limits=limits)
        except zipfile.BadZipFile:
            raise SystemExit("Input zip is invalid")
        except ZipValidationError as exc:
            raise SystemExit(f"{exc.code}: {exc.message}")
        runner = DockerRunner(
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
            logger=logging.getLogger("k2p.runner"),
        )

        workflow_dir = work_dir
        found = list(work_dir.rglob("workflow.knime"))
        if found:
            workflow_dir = found[0].parent

        try:
            result = runner.run_job("tmp-test", workflow_dir, out_dir)
        except RunnerError as exc:
            self.stderr.write(self.style.ERROR(f"Runner failed: {exc}"))
            if exc.stderr_tail:
                self.stderr.write(self.style.ERROR(exc.stderr_tail))
            raise SystemExit(1) from exc

        self.stdout.write(self.style.SUCCESS(f"OK: outputs in {out_dir}"))
        self.stdout.write(str(result))
