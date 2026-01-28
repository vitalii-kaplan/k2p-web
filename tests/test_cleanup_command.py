from __future__ import annotations

import time
from pathlib import Path
import os

from django.core.management import call_command
from django.conf import settings
from django.test import TestCase, override_settings


class CleanupCommandTests(TestCase):
    def test_cleanup_deletes_old_paths(self) -> None:
        now = time.time()
        old_ts = now - (8 * 24 * 60 * 60)

        with override_settings(JOB_STORAGE_ROOT=self._tmp_dir(), RESULT_STORAGE_ROOT=self._tmp_dir()):
            job_file = Path(settings.JOB_STORAGE_ROOT) / "jobs/abc/workflow.zip"
            result_file = Path(settings.RESULT_STORAGE_ROOT) / "jobs/abc/out.txt"
            job_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.parent.mkdir(parents=True, exist_ok=True)
            job_file.write_text("zip", encoding="utf-8")
            result_file.write_text("out", encoding="utf-8")

            os.utime(job_file, (old_ts, old_ts))
            os.utime(result_file, (old_ts, old_ts))

            call_command("k2p_cleanup", days=7)

            self.assertFalse(job_file.exists())
            self.assertFalse(result_file.exists())

    def test_cleanup_keeps_recent_paths(self) -> None:
        with override_settings(JOB_STORAGE_ROOT=self._tmp_dir(), RESULT_STORAGE_ROOT=self._tmp_dir()):
            job_file = Path(settings.JOB_STORAGE_ROOT) / "jobs/def/workflow.zip"
            result_file = Path(settings.RESULT_STORAGE_ROOT) / "jobs/def/out.txt"
            job_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.parent.mkdir(parents=True, exist_ok=True)
            job_file.write_text("zip", encoding="utf-8")
            result_file.write_text("out", encoding="utf-8")

            call_command("k2p_cleanup", days=7)

            self.assertTrue(job_file.exists())
            self.assertTrue(result_file.exists())

    def _tmp_dir(self) -> str:
        from tempfile import TemporaryDirectory

        tmp = TemporaryDirectory()
        # Keep reference alive for duration of test instance.
        if not hasattr(self, "_tmp_dirs"):
            self._tmp_dirs = []
        self._tmp_dirs.append(tmp)
        return tmp.name
