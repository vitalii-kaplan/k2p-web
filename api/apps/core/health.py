from __future__ import annotations

import tempfile
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

def healthz(_request):
    return JsonResponse({"status": "ok"})


def readyz(_request):
    checks: dict[str, str] = {}
    ok = True

    # DB check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["db"] = f"error: {exc}"
        ok = False

    # Storage roots check (writable)
    for key in ("JOB_STORAGE_ROOT", "RESULT_STORAGE_ROOT"):
        try:
            root = Path(getattr(settings, key))
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=root, delete=True):
                pass
            checks[key.lower()] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks[key.lower()] = f"error: {exc}"
            ok = False

    # Optional K8s check
    if getattr(settings, "READINESS_CHECK_K8S", False):
        try:
            p = subprocess.run(
                ["kubectl", "version", "--request-timeout=2s"],
                check=False,
                capture_output=True,
                text=True,
            )
            if p.returncode != 0:
                raise RuntimeError(p.stderr.strip() or "kubectl failed")
            checks["k8s"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["k8s"] = f"error: {exc}"
            ok = False

    return JsonResponse({"status": "ok" if ok else "fail", "checks": checks}, status=200 if ok else 503)
