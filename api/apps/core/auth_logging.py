from __future__ import annotations

import json
import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.utils import DatabaseError
from django.dispatch import receiver

logger = logging.getLogger("k2p.api")


def _request_meta(request: Any) -> dict[str, Any]:
    if request is None:
        return {"path": None, "remote_addr": None, "x_forwarded_for": None}
    return {
        "path": getattr(request, "path", None),
        "remote_addr": request.META.get("REMOTE_ADDR"),
        "x_forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR"),
    }


def _is_admin_login_request(request: Any) -> bool:
    path = getattr(request, "path", "") or ""
    return path.startswith("/admin/login")


def _load_user_debug(username: str | None) -> dict[str, Any]:
    if not username:
        return {"user_found": False}

    user_model = get_user_model()
    username_field = getattr(user_model, "USERNAME_FIELD", "username")

    try:
        user = user_model._default_manager.filter(**{username_field: username}).first()
    except (DatabaseError, ValueError, TypeError):
        return {"user_found": None}

    if user is None:
        return {"user_found": False}

    return {
        "user_found": True,
        "is_active": bool(getattr(user, "is_active", False)),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
    }


@receiver(user_login_failed, dispatch_uid="k2p_admin_login_failed")
def log_admin_login_failed(sender: Any, credentials: dict[str, Any], request: Any, **kwargs: Any) -> None:
    if not _is_admin_login_request(request):
        return

    username = credentials.get("username")
    payload = {
        "event": "admin_login_failed",
        "username": username,
        **_request_meta(request),
        **_load_user_debug(username if isinstance(username, str) else None),
    }
    logger.info(json.dumps(payload))


@receiver(user_logged_in, dispatch_uid="k2p_admin_login_succeeded")
def log_admin_login_succeeded(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    if not _is_admin_login_request(request):
        return

    payload = {
        "event": "admin_login_succeeded",
        "username": getattr(user, "get_username", lambda: None)(),
        "is_active": bool(getattr(user, "is_active", False)),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        **_request_meta(request),
    }
    logger.info(json.dumps(payload))
