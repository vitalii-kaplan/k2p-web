import datetime
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.jobs.management.commands.k2p_worker import Command
from apps.jobs.models import Job, JobSettingsMeta


class RetentionCleanupTests(TestCase):
    def test_cleanup_deletes_jobs_but_keeps_settings_meta(self) -> None:
        now = timezone.now()
        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs"
            result_root = Path(tmpdir) / "results"
            job_root.mkdir(parents=True, exist_ok=True)
            result_root.mkdir(parents=True, exist_ok=True)

            with override_settings(
                JOB_STORAGE_ROOT=job_root,
                RESULT_STORAGE_ROOT=result_root,
                RETENTION_FAILED_DAYS=1,
                RETENTION_SUCCEEDED_DAYS=-1,
            ):
                job = Job.objects.create(
                    status=Job.Status.FAILED,
                    finished_at=now - datetime.timedelta(days=2),
                )
                JobSettingsMeta.objects.create(
                    job_status=job.status,
                    file_name="settings.xml",
                )

                # create artifacts
                (job_root / f"jobs/{job.uuid}").mkdir(parents=True, exist_ok=True)
                (result_root / f"jobs/{job.uuid}").mkdir(parents=True, exist_ok=True)

                Command()._cleanup_old_jobs()

                self.assertFalse(Job.objects.filter(id=job.id).exists())
                self.assertTrue(JobSettingsMeta.objects.filter(file_name="settings.xml").exists())

    def test_cleanup_deletes_stale_running_jobs_but_keeps_recent_ones(self) -> None:
        now = timezone.now()
        with tempfile.TemporaryDirectory() as tmpdir:
            job_root = Path(tmpdir) / "jobs"
            result_root = Path(tmpdir) / "results"
            job_root.mkdir(parents=True, exist_ok=True)
            result_root.mkdir(parents=True, exist_ok=True)

            with override_settings(
                JOB_STORAGE_ROOT=job_root,
                RESULT_STORAGE_ROOT=result_root,
                RETENTION_FAILED_DAYS=1,
                RETENTION_SUCCEEDED_DAYS=-1,
            ):
                stale_started = Job.objects.create(
                    status=Job.Status.RUNNING,
                    started_at=now - datetime.timedelta(days=2),
                )
                stale_unstarted = Job.objects.create(status=Job.Status.RUNNING)
                Job.objects.filter(id=stale_unstarted.id).update(
                    created_at=now - datetime.timedelta(days=2)
                )
                recent = Job.objects.create(
                    status=Job.Status.RUNNING,
                    started_at=now - datetime.timedelta(hours=12),
                )

                Command()._cleanup_old_jobs()

                self.assertFalse(Job.objects.filter(id=stale_started.id).exists())
                self.assertFalse(Job.objects.filter(id=stale_unstarted.id).exists())
                self.assertTrue(Job.objects.filter(id=recent.id).exists())
