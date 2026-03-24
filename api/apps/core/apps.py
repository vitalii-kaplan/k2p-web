import logging
import os
import sys
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings

from .db_logging import log_db_settings
from .k2p_startup import check_version_and_export_handlers


SERVER_INIT_EXCLUDED_COMMANDS = {
    "check",
    "collectstatic",
    "createsuperuser",
    "dbshell",
    "flush",
    "makemigrations",
    "migrate",
    "shell",
    "test",
}


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        if "k2p_worker" in sys.argv:
            return
        if len(sys.argv) > 1 and sys.argv[1] in SERVER_INIT_EXCLUDED_COMMANDS:
            return
        if settings.DEBUG and os.environ.get("RUN_MAIN") != "true":
            return
        logger = logging.getLogger("k2p.api")
        log_db_settings(logger, event="api_db_settings")
        check_version_and_export_handlers(
            docker_bin=str(getattr(settings, "DOCKER_BIN", "docker")),
            image=str(getattr(settings, "K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main")),
            command=str(getattr(settings, "K2P_COMMAND", "")) or None,
            handlers_path=Path(getattr(settings, "K2P_HANDLERS_STATIC_FILE")),
            logger=logger,
        )
