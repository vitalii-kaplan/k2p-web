from __future__ import annotations

from apps.jobs.k8s import job_state, normalize_job_name


def test_normalize_job_name_sanitizes() -> None:
    assert normalize_job_name("ABC_123") == "k2p-abc-123"
    assert normalize_job_name("A" * 80).startswith("k2p-")
    assert len(normalize_job_name("A" * 80)) <= 63


def test_job_state_transitions() -> None:
    assert job_state({"status": {"succeeded": 1}}) == ("SUCCEEDED", 0)
    assert job_state({"status": {"failed": 2}}) == ("FAILED", 1)
    assert job_state({"status": {}}) == ("RUNNING", None)
