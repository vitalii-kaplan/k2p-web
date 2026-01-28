from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete job uploads/results older than a retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7, help="Retention window in days")

    def handle(self, *args, **opts):
        days = int(opts["days"])
        if days < 0:
            raise ValueError("--days must be >= 0")

        cutoff = time.time() - (days * 24 * 60 * 60)

        job_root = Path(settings.JOB_STORAGE_ROOT) / "jobs"
        result_root = Path(settings.RESULT_STORAGE_ROOT) / "jobs"

        deleted = 0
        deleted += self._cleanup_tree(job_root, cutoff)
        deleted += self._cleanup_tree(result_root, cutoff)

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} paths older than {days} days."))

    def _cleanup_tree(self, root: Path, cutoff: float) -> int:
        if not root.exists():
            return 0

        deleted = 0
        # Delete files/dirs older than cutoff by mtime (deepest first).
        for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            try:
                mtime = p.stat().st_mtime
            except FileNotFoundError:
                continue

            if mtime > cutoff:
                continue

            if p.is_file() or p.is_symlink():
                p.unlink(missing_ok=True)
                deleted += 1
            elif p.is_dir():
                # Remove empty dirs only (deleting is driven by file mtimes).
                try:
                    if not any(p.iterdir()):
                        p.rmdir()
                        deleted += 1
                except OSError:
                    pass

        return deleted
