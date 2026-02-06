# k2p-web

Minimal web API that converts KNIME workflows to Python/Jupyter via `knime2py`.

Users upload a sanitized workflow bundle (`.zip` containing `workflow.knime` + per-node `settings.xml`). The API stores the upload, enqueues a job, and a Kubernetes worker submits a K8s Job that runs `knime2py` in an isolated container. Results are returned as a ZIP.

## Features

* Upload workflow bundle and create a job
* Job status and metadata endpoint
* Result ZIP download when finished
* Kubernetes-backed worker loop (Job per request)

## API

Base path: `/api`

* `POST /api/jobs` — multipart form with `bundle` (zip)
* `GET /api/jobs/<uuid>` — job status/details
* `GET /api/jobs/<uuid>/result.zip` — result archive when `status == SUCCEEDED`

Health:

* `GET /healthz`

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
JOB_ID=$(echo "$JOB_JSON" | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -sS "http://127.0.0.1:8000/api/jobs/$JOB_ID" | python -m json.tool
curl -fL -o "result-$JOB_ID.zip" "http://127.0.0.1:8000/api/jobs/$JOB_ID/result.zip"
```

## Local Kubernetes (kind)

Prereqs: `docker`, `kubectl`, `kind`.

Create cluster:

```bash
./scripts/kind-create.sh
```

Run one k2p job directly (debug):

```bash
./scripts/kind-run-k2p-job.sh
```

## Storage layout

Local default (dev):

* uploads: `var/jobs/jobs/<uuid>/...`
* results: `var/results/jobs/<uuid>/...`

## Settings

Read from Django settings (environment or defaults):

* `JOB_STORAGE_ROOT` — where uploads are stored (default `var/jobs`)
* `RESULT_STORAGE_ROOT` — where results are written (default `var/results`)
* `REPO_ROOT` — repo root path for K8s hostPath mapping (dev-only)
* `K8S_NAMESPACE` — k8s namespace for jobs (default `k2p`)
* `K2P_IMAGE` — container image to run `knime2py` (e.g. `ghcr.io/vitalii-kaplan/knime2py:main`)

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
docker compose exec -T worker env | grep K2P
docker compose exec -T worker sh -lc 'docker ps'
```
