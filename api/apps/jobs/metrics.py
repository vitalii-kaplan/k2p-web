from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


JOB_CREATED_TOTAL = Counter(
    "k2p_job_created_total",
    "Total number of jobs created",
)

JOB_FINISHED_TOTAL = Counter(
    "k2p_job_finished_total",
    "Total number of jobs finished",
    ["status"],
)

JOB_DURATION_SECONDS = Histogram(
    "k2p_job_duration_seconds",
    "Job duration in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)

JOB_QUEUE_DEPTH = Gauge(
    "k2p_job_queue_depth",
    "Number of jobs in QUEUED state",
)

ENQUEUE_REJECTED_TOTAL = Counter(
    "k2p_enqueue_rejected_total",
    "Total number of job enqueue rejections",
)

# Worker-specific metrics (served from worker /metrics endpoint)
JOB_QUEUE_WAIT_SECONDS = Histogram(
    "k2p_job_queue_wait_seconds",
    "Time from job creation to worker pickup/start (seconds)",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)

JOB_RUN_SECONDS = Histogram(
    "k2p_job_run_seconds",
    "Time from job start to finish (seconds)",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)

JOB_END_TO_END_SECONDS = Histogram(
    "k2p_job_end_to_end_seconds",
    "Time from job creation to finish (seconds)",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)

WORKER_HEARTBEAT_TIMESTAMP_SECONDS = Gauge(
    "k2p_worker_heartbeat_timestamp_seconds",
    "Worker heartbeat (Unix timestamp)",
)

WORKER_ERRORS_TOTAL = Counter(
    "k2p_worker_errors_total",
    "Total number of worker loop errors",
)

K8S_JOB_START_LATENCY_SECONDS = Histogram(
    "k2p_k8s_job_start_latency_seconds",
    "Time spent submitting job to Kubernetes (seconds)",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)

KUBECTL_FAILURES_TOTAL = Counter(
    "k2p_kubectl_failures_total",
    "Total number of kubectl failures",
)

K2P_EXIT_CODE_TOTAL = Counter(
    "k2p_exit_code_total",
    "Total number of job exit codes",
    ["exit_code"],
)

K2P_ERROR_TOTAL = Counter(
    "k2p_error_total",
    "Total number of knime2py job failures",
)
