from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.jobs.management.commands.k2p_worker import Command
from apps.jobs.models import Job
from apps.jobs.runner import RunnerError
from apps.jobs.security import ZipValidationError


class WorkerLogsTests(TestCase):
    def test_job_picked_and_finished_logged(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED, input_key="jobs/x/test.zip")
        cmd = Command()

        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs" / "x"
            job_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(job_root / "test.zip", "w") as zf:
                zf.writestr("workflow.knime", "<root></root>")

            with override_settings(JOB_STORAGE_ROOT=tmpdir, RESULT_STORAGE_ROOT=tmpdir):
                with patch("apps.jobs.management.commands.k2p_worker.DockerRunner.run_job", return_value={"exit_code": 0}):
                    with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                        cmd._run_one(runner=cmd._build_runner())

        calls = [c[0][0] for c in logger.info.call_args_list]
        payloads = [json.loads(c) for c in calls]
        events = {p.get("event") for p in payloads}
        self.assertIn("job_picked", events)
        self.assertIn("job_finished", events)

    def test_job_failed_logged(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED, input_key="jobs/y/test.zip")
        cmd = Command()

        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs" / "y"
            job_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(job_root / "test.zip", "w") as zf:
                zf.writestr("workflow.knime", "<root></root>")

            with override_settings(JOB_STORAGE_ROOT=tmpdir, RESULT_STORAGE_ROOT=tmpdir):
                err = RunnerError("boom", exit_code=7, stderr_tail="oops")
                with patch("apps.jobs.management.commands.k2p_worker.DockerRunner.run_job", side_effect=err):
                    with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                        cmd._run_one(runner=cmd._build_runner())

        payload = json.loads(logger.info.call_args[0][0])
        self.assertEqual(payload["event"], "job_finished")
        self.assertEqual(payload["status"], "FAILED")

    def test_job_timeout_marks_failed(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED, input_key="jobs/z/test.zip")
        cmd = Command()

        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs" / "z"
            job_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(job_root / "test.zip", "w") as zf:
                zf.writestr("workflow.knime", "<root></root>")

            with override_settings(JOB_STORAGE_ROOT=tmpdir, RESULT_STORAGE_ROOT=tmpdir):
                err = RunnerError("timeout after 1s", exit_code=None, stderr_tail="timeout")
                with patch("apps.jobs.management.commands.k2p_worker.DockerRunner.run_job", side_effect=err):
                    cmd._run_one(runner=cmd._build_runner())

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn("timeout", job.error_message)

    def test_zip_validation_error_marks_failed(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED, input_key="jobs/a/test.zip")
        cmd = Command()

        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs" / "a"
            job_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(job_root / "test.zip", "w") as zf:
                zf.writestr("workflow.knime", "<root></root>")

            with override_settings(JOB_STORAGE_ROOT=tmpdir, RESULT_STORAGE_ROOT=tmpdir):
                err = ZipValidationError("zip_bomb", "Zip exceeds maximum total uncompressed size.")
                with patch("apps.jobs.management.commands.k2p_worker.safe_extract_zip", side_effect=err):
                    cmd._run_one(runner=cmd._build_runner())

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual(job.error_code, "zip_bomb")
