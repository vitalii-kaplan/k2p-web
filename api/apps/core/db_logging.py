from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings


def log_db_settings(logger: logging.Logger, *, event: str = "db_settings") -> None:
    db = settings.DATABASES.get("default", {})
    engine = str(db.get("ENGINE", ""))

    payload: dict[str, str] = {
        "event": event,
        "engine": engine,
    }

    if "sqlite" in engine:
        name = str(db.get("NAME", ""))
        payload["name"] = str(Path(name).resolve()) if name else ""
    else:
        payload["name"] = str(db.get("NAME", ""))
        payload["host"] = str(db.get("HOST", ""))
        payload["port"] = str(db.get("PORT", ""))

    logger.info(json.dumps(payload))
