from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml  # if you don’t want this dep, I’ll show a pure-string variant


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def normalize_job_name(job_id: str) -> str:
    # k8s DNS-1123 label: lowercase alnum + '-'
    base = re.sub(r"[^a-z0-9-]+", "-", job_id.lower())
    return ("k2p-" + base)[:63].rstrip("-")


def render_job_manifest(
    *,
    namespace: str,
    job_name: str,
    image: str,
    in_host_path: str,
    in_container_path: str,
    out_host_dir: str,
) -> dict:
    # Note: your CLI extracts zip to tempfile → needs writable /tmp even if root fs is RO.
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace, "labels": {"app": "k2p"}},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": {"app": "k2p", "job-name": job_name}},
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "k2p",
                            "image": image,
                            "args": ["--in-zip", in_container_path, "--out", "/out"],
                            "env": [{"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}],
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 65532,
                                "runAsGroup": 65532,
                                "readOnlyRootFilesystem": True,
                                "allowPrivilegeEscalation": False,
                            },
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "256Mi"},
                                "limits": {"cpu": "1", "memory": "1Gi"},
                            },
                            "volumeMounts": [
                                {"name": "inzip", "mountPath": in_container_path, "readOnly": True},
                                {"name": "outdir", "mountPath": "/out"},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "inzip",
                            "hostPath": {"path": in_host_path, "type": "File"},
                        },
                        {
                            "name": "outdir",
                            "hostPath": {"path": out_host_dir, "type": "DirectoryOrCreate"},
                        },
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
        },
    }


def kubectl_apply(manifest: dict) -> tuple[bool, str]:
    p = _run(["kubectl", "apply", "-f", "-"],)
    # We'll pipe via stdin below; subprocess wrapper needs input.
    raise RuntimeError("Use kubectl_apply_yaml() instead.")


def kubectl_apply_yaml(manifest: dict) -> tuple[bool, str, str]:
    yml = yaml.safe_dump(manifest, sort_keys=False)
    p = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=yml,
        text=True,
        capture_output=True,
    )
    return (p.returncode == 0, p.stdout, p.stderr)


def kubectl_get_job(namespace: str, job_name: str) -> dict | None:
    p = _run(["kubectl", "-n", namespace, "get", "job", job_name, "-o", "json"])
    if p.returncode != 0:
        return None
    return json.loads(p.stdout)


def job_state(job_json: dict) -> tuple[str, int | None]:
    status = job_json.get("status", {})
    if status.get("succeeded", 0) >= 1:
        return ("SUCCEEDED", 0)
    if status.get("failed", 0) >= 1:
        return ("FAILED", 1)
    return ("RUNNING", None)
