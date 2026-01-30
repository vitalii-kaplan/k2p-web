from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.jobs.management.commands.k2p_worker import Command
from apps.jobs.models import Job


class WorkerLogsTests(TestCase):
    def test_job_picked_and_k8s_created_logged(self) -> None:
        job = Job.objects.create(status=Job.Status.QUEUED)
        cmd = Command()

        with override_settings(
            JOB_STORAGE_ROOT="var/jobs",
            RESULT_STORAGE_ROOT="var/results",
            REPO_ROOT=".",
        ):
            with patch("apps.jobs.management.commands.k2p_worker.kubectl_apply_yaml", return_value=(True, "", "")):
                with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                    cmd._submit_one(ns="k2p", image="img")

        calls = [c[0][0] for c in logger.info.call_args_list]
        payloads = [json.loads(c) for c in calls]
        events = {p.get("event") for p in payloads}
        self.assertIn("job_picked", events)
        self.assertIn("k8s_job_created", events)

    def test_job_finished_logged(self) -> None:
        started = timezone.now()
        job = Job.objects.create(
            status=Job.Status.RUNNING,
            k8s_job_name="k2p-123",
            started_at=started,
        )
        cmd = Command()

        with patch("apps.jobs.management.commands.k2p_worker.kubectl_get_job", return_value={"status": {"succeeded": 1}}):
            with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                cmd._reconcile_running(ns="k2p")

        payload = json.loads(logger.info.call_args[0][0])
        self.assertEqual(payload["event"], "job_finished")
        self.assertEqual(payload["status"], "SUCCEEDED")
