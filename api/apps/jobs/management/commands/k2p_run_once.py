from __future__ import annotations

import uuid
from pathlib import Path
import zipfile
import shutil

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.jobs.runner import DockerRunner, RunnerError


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
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if name.startswith("__MACOSX/") or "/__MACOSX/" in name or Path(name).name.startswith("._"):
                        continue
                    zf.extract(info, work_dir)
        except zipfile.BadZipFile:
            raise SystemExit("Input zip is invalid")
        runner = DockerRunner(
            docker_bin=getattr(settings, "DOCKER_BIN", "docker"),
            image=getattr(settings, "K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main"),
            timeout_s=int(getattr(settings, "K2P_TIMEOUT_SECS", 300)),
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

        try:
            result = runner.run_job("tmp-test", work_dir, out_dir)
        except RunnerError as exc:
            self.stderr.write(self.style.ERROR(f"Runner failed: {exc}"))
            if exc.stderr_tail:
                self.stderr.write(self.style.ERROR(exc.stderr_tail))
            raise SystemExit(1) from exc

        self.stdout.write(self.style.SUCCESS(f"OK: outputs in {out_dir}"))
        self.stdout.write(str(result))
