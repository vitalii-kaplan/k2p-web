from __future__ import annotations

import os
import sys
from pathlib import Path

import django
from django.conf import settings

root = Path(__file__).resolve().parents[1]
api_dir = root / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "k2pweb.settings")


def pytest_configure() -> None:
    django.setup()
    # Allow Django test client host header.
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]
