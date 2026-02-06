# k2p-web

Minimal web API that converts KNIME workflows to Python/Jupyter via `knime2py`.

Users upload a sanitized workflow bundle (`.zip` containing `workflow.knime` at the top level + per-node `settings.xml`). The API stores the upload, enqueues a job, and a worker runs `knime2py` in an isolated Docker container. Results are returned as a ZIP.

## Features

* Upload workflow bundle and create a job
* Job status and metadata endpoint
* Result ZIP download when finished
* Docker-backed worker loop (job per request)

## API

Base path: `/api`

* `POST /api/jobs` — multipart form with `bundle` (zip)
* `GET /api/jobs/<uuid>` — job status/details
* `GET /api/jobs/<uuid>/result.zip` — result archive when `status == SUCCEEDED`

Health:

* `GET /healthz`
* `GET /readyz`

## Local development

Create venv and install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run migrations:

```bash
python api/manage.py migrate
```

Start the API:

```bash
python api/manage.py runserver
```

Start the worker (in another terminal):

```bash
python api/manage.py k2p_worker
```

Create a job and download results:

```bash
JOB_JSON=$(curl -sS -X POST -F "bundle=@tests/data/discounts.zip" http://127.0.0.1:8000/api/jobs)
JOB_ID=$(echo "$JOB_JSON" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)

curl -sS "http://127.0.0.1:8000/api/jobs/$JOB_ID" | python -m json.tool
curl -fL -o "result-$JOB_ID.zip" "http://127.0.0.1:8000/api/jobs/$JOB_ID/result.zip"
```

## Storage layout

Local default (dev):

* uploads: `var/jobs/jobs/<uuid>/...`
* results: `var/results/jobs/<uuid>/...`

## Settings

Read from Django settings (environment or defaults):

* `JOB_STORAGE_ROOT` — where uploads are stored (default `var/jobs`)
* `RESULT_STORAGE_ROOT` — where results are written (default `var/results`)
* `K2P_IMAGE` — container image to run `knime2py` (e.g. `ghcr.io/vitalii-kaplan/knime2py:main`)
* `K2P_TIMEOUT_SECS`, `K2P_CPU`, `K2P_MEMORY`, `K2P_PIDS_LIMIT` — Docker runner limits
* `K2P_COMMAND`, `K2P_ARGS_TEMPLATE` — optional overrides for the runner
* `HOST_JOB_STORAGE_ROOT`, `HOST_RESULT_STORAGE_ROOT` — host paths for Docker-in-Docker runner mounts

## Tests

```bash
python -m pytest
```

UI unit tests require Node.js + npm (install via `brew install node`).

```bash
npm install
npm run test:ui
```

## Debugging (runner)

```bash
docker compose -f docker-compose.prod.nginx.yml exec -T worker env | grep K2P
docker compose -f docker-compose.prod.nginx.yml exec -T worker sh -lc 'docker ps'
```
