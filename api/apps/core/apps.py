import logging
import os
import sys

from django.apps import AppConfig
from django.conf import settings

from .db_logging import log_db_settings

class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        if "k2p_worker" in sys.argv:
            return
        if settings.DEBUG and os.environ.get("RUN_MAIN") != "true":
            return
        log_db_settings(logging.getLogger("k2p.api"), event="api_db_settings")
