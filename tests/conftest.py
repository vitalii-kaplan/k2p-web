from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[1]
api_dir = root / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))


def pytest_load_initial_conftests(early_config, parser, args) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "k2pweb.settings")
    os.environ.setdefault("DEBUG", "1")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture(autouse=True)
def _allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]

