# AGENTS.md

Project-specific guidance for coding agents working in this repository.

## Source of truth

- Treat the code in this repository as the source of truth.
- External summaries, chats, or generated docs may be useful hints, but they must be verified against the current code before being relied on.

## Quick start (preferred commands)

- Use Make targets instead of ad-hoc commands when possible.
- Local API: `make server`
- Local worker: `make worker`
- Tests: `make test` (or `make test-py`, `make test-ui`)
- Lint/format: `make lint`, `make fmt`
- Docker dev stack: `make docker-dev-up`, logs via `make docker-api-logs` and `make docker-worker-logs`
- Production compose: `make prod-up`, `make prod-down`, `make prod-check`

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
- Docker runner requires host-visible paths for job/result storage:
  - `HOST_JOB_STORAGE_ROOT`, `HOST_RESULT_STORAGE_ROOT` should be set when running worker containers via Docker.
- Schema convention: every table must use an auto-increment numeric primary key (e.g., `BigAutoField`), even if there is another unique identifier like a UUID.

## Product flow

- The main user flow is: upload a workflow ZIP, create a job, process it in the worker, then download results when ready.
- Jobs are stored in the `Job` model with status lifecycle:
  `QUEUED` -> `RUNNING` -> `SUCCEEDED` or `FAILED`.
- Jobs are addressed externally by UUID, while the database primary key remains numeric.

## Metrics conventions

- API (`:8000`, django-prometheus) exposes DB-snapshot gauges such as:
  - `k2p_jobs_by_state`
  - `k2p_last_job_finished_timestamp_seconds`
- Worker (`:8001`) exposes process-local counters/histograms such as:
  - `k2p_job_finished_total`
  - `k2p_job_duration_seconds_*`
- Counter resets after restart are expected; do not treat them as data loss.

## Runner behavior

- Jobs are executed via Docker (`docker run`) inside the worker process.
- Uploaded ZIP must contain `workflow.knime` at the top level (server-side validation enforces this).
- The worker unzips into `_work`, searches for `workflow.knime`, and passes its parent directory to the runner.
- Runner isolation matters. Preserve security-related Docker flags unless the task explicitly requires changing them.

## API and routes

- UI entrypoint: `/`
- Main API routes:
  - `POST /api/jobs`
  - `GET /api/jobs/<uuid>`
  - `GET /api/jobs/<uuid>/logs`
  - `GET /api/jobs/<uuid>/result.zip`
- Operational routes:
  - `/healthz`
  - `/readyz`
  - `/meta/handlers.csv`
  - `/admin/`
- `/api/schema/` is exposed only when `DEBUG` is on or `EXPOSE_SCHEMA=1`.

## Deployment model

- Production uses Docker Compose with separate `api`, `worker`, `postgres`, and `nginx` services.
- Nginx serves `/static/` from the shared static volume and proxies application traffic to the API container.
- Production stack commands must use the explicit Compose project name `k2pweb`; do not rely on the directory-derived default project name.

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

## Naming conventions

- Use `k2pweb` for machine identifiers:
  compose project names, Django module/package names, database names, and similar runtime/internal IDs.
- Use `k2p-web` for human-facing branding:
  README text, UI copy, site titles, and similar product-label usage.
- Do not change between these forms casually. Mixing them in runtime identifiers can create parallel Docker Compose stacks such as `k2pweb-*` and `k2p-web-*`.
