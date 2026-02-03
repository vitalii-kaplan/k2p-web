# AGENTS.md

Project-specific guidance for coding agents working in this repository.

## Quick start (preferred commands)

- Use Make targets instead of ad-hoc commands when possible.
- Local API: `make server`
- Local worker: `make worker`
- Tests: `make test` (or `make test-py`, `make test-ui`)
- Lint/format: `make lint`, `make fmt`
- Docker dev stack: `make docker-dev-up`, logs via `make docker-api-logs` and `make docker-worker-logs`

## Python environment

- Prefer the project venv at `.venv/`.
- The Makefile already prefers `.venv/bin/python`; do not bypass this unless asked.
- Install dependencies with `pip install -e .[dev]`.

## Database and shared state

- API and worker must point to the same DB/state source.
- For SQLite, use absolute/resolved paths (settings resolve `SQLITE_PATH` under `REPO_ROOT`).
- Startup logs include:
  - `api_db_settings` (API process)
  - `worker_db_settings` (worker process)
- If metrics disagree between `:8000` and `:8001`, compare these two log events first.

## Metrics conventions

- API (`:8000`, django-prometheus) exposes DB-snapshot gauges such as:
  - `k2p_jobs_by_state`
  - `k2p_last_job_finished_timestamp_seconds`
- Worker (`:8001`) exposes process-local counters/histograms such as:
  - `k2p_job_finished_total`
  - `k2p_job_duration_seconds_*`
- Counter resets after restart are expected; do not treat them as data loss.

## Testing rules

- `pytest.ini` configures `DJANGO_SETTINGS_MODULE=k2pweb.settings`.
- Avoid DB access at import time (module import should not execute queries).
- Metrics collector registration is guarded during pytest; preserve that behavior.
- When adding new tests for Django models/views, use `@pytest.mark.django_db` or DB fixtures as needed.

## Logging

- `k2p.api` and `k2p.worker` loggers are configured to INFO in Django settings.
- Keep logs structured and compact (JSON payloads for operational events are preferred).
- Do not log secrets (passwords/tokens); DB logging should stay sanitized.

## Change hygiene

- Keep edits minimal and focused on the requested task.
- Do not revert unrelated local changes.
- If unexpected modifications appear that you did not make, stop and ask the user before continuing.
