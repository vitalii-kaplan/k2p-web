from __future__ import annotations

import importlib


def test_jobs_serializers_import_does_not_touch_db() -> None:
    import apps.jobs.serializers as serializers_module

    importlib.reload(serializers_module)
