## Add these before you start a frontend

### 0) Decide “one command” workflows

Make it trivial to do the basics:

* `make dev` (or `./scripts/dev.sh`) → run server + worker
* `make test` → run tests with the right interpreter
* `make prod-check` (smoke checks using prod compose)

This prevents the Anaconda/venv confusion from coming back.

### 1) Configuration hygiene (12-factor basics)

Right now you have paths like `RESULT_STORAGE_ROOT`, `MEDIA_ROOT`, etc. Lock this down:

* `api/k2pweb/settings.py` reads from environment (or `.env` for local)
* `api/k2pweb/settings_local.py` optional, gitignored
* `.env.example` committed

### 2) DB migrations and fixtures

Before pushing a repo publicly:

* run `python api/manage.py makemigrations` and commit migrations
* add a minimal “dev DB” flow (sqlite for local is fine; postgres later)
* optional: `scripts/reset-db.sh` for local

### 3) Add a cleanup/retention mechanism (even stubbed)

You’re storing uploads and results on disk. You need:

* a management command: `python api/manage.py k2p_cleanup --days 7`
* tests for “older than retention gets deleted”
  Even if production uses object storage later, the API contract needs it.

### 4) Job queue backpressure (MVP guardrail)

You already planned “reject if queue full”. Put it in now, even with a constant like:

* `MAX_QUEUED_JOBS = 50`
* if exceeded, POST returns `429` with a clear error code

This is easy now, painful later.

### 5) API contract polish

Add these small endpoints now (frontend will need them):

* `GET /api/jobs/<id>/result.zip` (done)
* `GET /api/jobs/<id>` (done)
* `GET /api/jobs/<id>/logs` (even if it returns `stdout_tail/stderr_tail` from DB only)

Also add `OpenAPI schema` generation (DRF has it; you already have `generateschema` command).

### 6) CI that matches reality

In GitHub Actions:

* run `python -m pytest` (not `pytest`)
* run `ruff` or `flake8` + `black` (or `ruff format`)
* run a minimal integration test that starts the prod compose stack and runs one job (optional; can be nightly)

### 7) Licensing, security, and docs

* LICENSE (MIT/Apache-2.0 — pick one)
* SECURITY.md (basic reporting instructions)
* README: local dev, Docker runner flow, API endpoints, retention policy, limits

## About “new repo and push”

Yes. Do it early, before history gets messy.

## After these, you’re ready for the client

At that point you can add a simple React UI (still very common) or even start with a static HTML page + fetch calls and upgrade later.

If you want, I can propose:

* a minimal `pyproject.toml` (tooling + dependencies + scripts)
* a `Makefile`
* and two GitHub Actions workflows: `ci.yml` + `docker-api.yml` (later).
