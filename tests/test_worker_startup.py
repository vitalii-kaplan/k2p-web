from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.jobs.management.commands.k2p_worker import Command
from apps.jobs.runner import RunnerError


class WorkerStartupTests(SimpleTestCase):
    def test_warmup_calls_ensure_image_and_logs_success(self) -> None:
        cmd = Command()
        runner = cmd._build_runner()

        with patch.object(runner, "ensure_image", return_value=None) as ensure_image:
            with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                cmd._warmup_runner(runner)

        ensure_image.assert_called_once_with()
        info_payloads = [json.loads(call[0][0]) for call in logger.info.call_args_list]
        events = [p["event"] for p in info_payloads]
        self.assertEqual(events, ["runner_warmup_start", "runner_warmup_ok"])

    def test_warmup_raises_runtime_error_on_image_failure(self) -> None:
        cmd = Command()
        runner = cmd._build_runner()

        err = RunnerError("image_pull_failed", exit_code=1)
        with patch.object(runner, "ensure_image", side_effect=err):
            with patch("apps.jobs.management.commands.k2p_worker.logger") as logger:
                with self.assertRaisesRegex(RuntimeError, "runner warmup failed"):
                    cmd._warmup_runner(runner)

        error_payload = json.loads(logger.error.call_args[0][0])
        self.assertEqual(error_payload["event"], "runner_warmup_failed")
        self.assertEqual(error_payload["exit_code"], 1)
