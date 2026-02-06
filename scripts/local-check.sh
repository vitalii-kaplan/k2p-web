#!/usr/bin/env bash
set -euo pipefail

# ----------------------------
# Config (env overrides)
# ----------------------------
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose-local.yml}"
API_URL="${API_URL:-http://127.0.0.1:8000}"

WIPE_VOLUMES="${WIPE_VOLUMES:-0}"         # 1 => docker compose down -v
START_WORKER="${START_WORKER:-0}"         # 1 => start worker and verify it stays running
SKIP_HTTP="${SKIP_HTTP:-0}"               # 1 => do not curl endpoints
CHECK_READYZ="${CHECK_READYZ:-1}"         # 1 => also check /readyz
HTTP_RETRIES="${HTTP_RETRIES:-60}"        # retries for HTTP readiness
HTTP_SLEEP="${HTTP_SLEEP:-1}"             # seconds between HTTP retries

MIGRATE_SKIP_CHECKS="${MIGRATE_SKIP_CHECKS:-0}" # 1 => use --skip-checks
CHECK_JOB_RUN="${CHECK_JOB_RUN:-1}"
JOB_FIXTURE_ZIP="${JOB_FIXTURE_ZIP:-tests/data/discounts.zip}"
JOB_WAIT_SECS="${JOB_WAIT_SECS:-120}"

# ----------------------------
# Helpers
# ----------------------------
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/.." && pwd)"
DC=(docker compose -f "${repo_root}/${COMPOSE_FILE}")

die() { echo "ERROR: $*" >&2; exit 1; }

project_name() {
  "${DC[@]}" config 2>/dev/null | awk '/^name: /{print $2; exit}'
}

container_id_for_service() {
  local svc="$1"
  local cid=""

  # Compose ps sometimes hides non-running containers unless -a
  cid="$("${DC[@]}" ps -a -q "$svc" 2>/dev/null | head -n1 || true)"
  if [[ -n "$cid" ]]; then
    echo "$cid"
    return 0
  fi

  # Fallback: labels (works even with container_name)
  local proj
  proj="$(project_name)"
  [[ -z "$proj" ]] && return 1

  cid="$(docker ps -aq \
    --filter "label=com.docker.compose.project=${proj}" \
    --filter "label=com.docker.compose.service=${svc}" \
    | head -n1 || true)"
  [[ -n "$cid" ]] && echo "$cid"
}

inspect_one_line() {
  local cid="$1"
  docker inspect -f 'status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} restart={{.RestartCount}}' "$cid" 2>/dev/null || true
}

wait_service_healthy() {
  local svc="$1"
  local tries="${2:-60}"
  local sleep_s="${3:-1}"

  local cid health
  cid="$(container_id_for_service "$svc" || true)"
  [[ -z "$cid" ]] && die "No container id for service '$svc'"

  for ((i=1; i<=tries; i++)); do
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$cid" 2>/dev/null || true)"
    if [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then
      echo "$cid"
      return 0
    fi
    if [[ "$health" == "unhealthy" ]]; then
      echo "  $svc is unhealthy. Logs:" >&2
      "${DC[@]}" logs --tail=200 "$svc" >&2 || true
      return 1
    fi
    sleep "$sleep_s"
  done

  echo "  timed out waiting for $svc health=healthy (last=$health)" >&2
  "${DC[@]}" logs --tail=200 "$svc" >&2 || true
  return 1
}

wait_container_running() {
  local svc="$1"
  local tries="${2:-40}"
  local sleep_s="${3:-1}"

  local cid status running exitcode
  for ((i=1; i<=tries; i++)); do
    cid="$(container_id_for_service "$svc" || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
      running="$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || true)"
      exitcode="$(docker inspect -f '{{.State.ExitCode}}' "$cid" 2>/dev/null || true)"

      if [[ "$running" == "true" ]]; then
        echo "$cid"
        return 0
      fi

      if [[ "$status" == "exited" ]]; then
        echo "  $svc exited early (exit=$exitcode). Logs:" >&2
        "${DC[@]}" logs --tail=200 "$svc" >&2 || true
        return 1
      fi
    fi
    sleep "$sleep_s"
  done

  echo "  timed out waiting for $svc to be running." >&2
  "${DC[@]}" ps -a >&2 || true
  [[ -n "${cid:-}" ]] && echo "  last: cid=$cid $(inspect_one_line "$cid")" >&2
  "${DC[@]}" logs --tail=200 "$svc" >&2 || true
  return 1
}

dump_api_debug() {
  echo "---- DEBUG: compose ps ----" >&2
  "${DC[@]}" ps -a >&2 || true
  echo "---- DEBUG: api logs ----" >&2
  "${DC[@]}" logs --tail=200 api >&2 || true
  echo "---- DEBUG: postgres logs ----" >&2
  "${DC[@]}" logs --tail=80 postgres >&2 || true

  local cid
  cid="$(container_id_for_service api || true)"
  if [[ -n "$cid" ]]; then
    echo "---- DEBUG: api inspect ----" >&2
    echo "cid=$cid $(inspect_one_line "$cid")" >&2
  fi
}

# Retry loop: must get HTTP 200
http_wait_200() {
  local url="$1"
  local tries="${2:-60}"
  local sleep_s="${3:-1}"

  local code rc last_err=""
  local err_file
  err_file="$(mktemp)"

  for ((i=1; i<=tries; i++)); do
    : >"$err_file"

    set +e
    code="$(
      curl -s \
        --connect-timeout 1 \
        --max-time 2 \
        -o /dev/null -w '%{http_code}' \
        "$url" 2>"$err_file"
    )"
    rc=$?
    set -e

    if [[ $rc -eq 0 && "$code" == "200" ]]; then
      echo "  GET $url : 200 OK"
      rm -f "$err_file"
      return 0
    fi

    # Keep last curl error (for final report), but don't spam on retries.
    if [[ -s "$err_file" ]]; then
      last_err="$(tail -n 1 "$err_file")"
    else
      last_err="curl rc=$rc http_code=$code"
    fi

    # If the container died, fail fast with logs
    local api_cid status running
    api_cid="$(container_id_for_service api || true)"
    if [[ -n "$api_cid" ]]; then
      status="$(docker inspect -f '{{.State.Status}}' "$api_cid" 2>/dev/null || true)"
      running="$(docker inspect -f '{{.State.Running}}' "$api_cid" 2>/dev/null || true)"
      if [[ "$running" != "true" || "$status" == "exited" ]]; then
        echo "  GET $url : api container not running (last_code=$code)" >&2
        dump_api_debug
        rm -f "$err_file"
        return 1
      fi
    fi

    # Transient not-ready: retry
    sleep "$sleep_s"
  done

  echo "  GET $url : did not become 200 within ${tries}s (last_code=$code)" >&2
  echo "  last curl error: $last_err" >&2
  dump_api_debug
  rm -f "$err_file"
  return 1
}

run_job_smoke_test() {
  echo "Step 10: Job smoke test (upload + result.zip availability)"
  local fixture="${repo_root}/${JOB_FIXTURE_ZIP}"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"

  local job_json job_id status code
  job_json="$(curl -sS -X POST -F "bundle=@${fixture}" "${API_URL}/api/jobs")"
  job_id="$(echo "$job_json" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$job_id" ]] || die "failed to parse job id from response: $job_json"
  echo "  job_id=$job_id"

  local deadline=$((SECONDS + JOB_WAIT_SECS))
  status=""
  while (( SECONDS < deadline )); do
    status="$(curl -sS "${API_URL}/api/jobs/$job_id" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    if [[ "$status" == "SUCCEEDED" ]]; then
      break
    fi
    if [[ "$status" == "FAILED" ]]; then
      local err
      err="$(curl -sS "${API_URL}/api/jobs/$job_id" | sed -n 's/.*"error_message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
      die "job failed: $err"
    fi
    sleep 1
  done

  [[ "$status" == "SUCCEEDED" ]] || die "job did not finish within ${JOB_WAIT_SECS}s (last=$status)"
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/api/jobs/$job_id/result.zip" || echo "000")"
  [[ "$code" == "200" ]] || die "result.zip not downloadable (status=$code)"
  echo "  GET /api/jobs/$job_id/result.zip : 200 OK"
  echo
}

# ----------------------------
# Start
# ----------------------------
cd "$repo_root"

echo "Repo: $repo_root"
echo "Docker context: $(docker context show)"
echo "Compose file: ${COMPOSE_FILE}"
echo "API_URL: ${API_URL}"
echo "WIPE_VOLUMES=${WIPE_VOLUMES} START_WORKER=${START_WORKER} SKIP_HTTP=${SKIP_HTTP} CHECK_READYZ=${CHECK_READYZ}"
echo

if [[ -f .env ]]; then
  echo ".env checks:"
  echo -n "  DJANGO_DEBUG="; grep -E '^DJANGO_DEBUG=' .env | tail -n1 | cut -d= -f2- || echo "(missing)"
  echo -n "  DB_ENGINE=";    grep -E '^DB_ENGINE=' .env | tail -n1 | cut -d= -f2- || echo "(missing)"
  if grep -qE '^DJANGO_SECRET_KEY=' .env; then
    echo "  DJANGO_SECRET_KEY=set"
  else
    echo "  DJANGO_SECRET_KEY=missing"
  fi
  echo
else
  echo "WARN: .env not found in repo root."
  echo
fi

echo "Step 1: Teardown"
if [[ "$WIPE_VOLUMES" == "1" ]]; then
  echo "  Running: docker compose down -v --remove-orphans"
  "${DC[@]}" down -v --remove-orphans
else
  echo "  Running: docker compose down --remove-orphans"
  "${DC[@]}" down --remove-orphans
fi
echo

echo "Step 2: Start Postgres"
"${DC[@]}" up -d postgres
pg_cid="$(wait_service_healthy postgres 60 1)"
echo "  postgres container: $pg_cid"
echo "  postgres is healthy"
echo

echo "Step 3: Verify compose environment for api"
"${DC[@]}" run --rm --no-deps api env | egrep '^(DB_ENGINE|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|DJANGO_DEBUG|DJANGO_SECRET_KEY)=' || true
echo

echo "Step 4: Run migrations"
if [[ "$MIGRATE_SKIP_CHECKS" == "1" ]]; then
  "${DC[@]}" run --rm --no-deps api python manage.py migrate --skip-checks
else
  "${DC[@]}" run --rm --no-deps api python manage.py migrate
fi
echo

echo "Step 5: Validate Postgres tables"
DB_USER="${DB_USER:-k2pweb}"
DB_NAME="${DB_NAME:-k2pweb}"
"${DC[@]}" exec -T postgres psql -U "${DB_USER}" -d "${DB_NAME}" -c '\dt'
echo

echo "Step 6: Start API"
"${DC[@]}" up -d api
api_cid="$(wait_container_running api 40 1)"
echo "  api container: $api_cid"
echo "  api is running"
echo

# Readiness is *HTTP*, not “container running”.
if [[ "$SKIP_HTTP" != "1" ]]; then
  echo "Step 7: HTTP readiness"
  http_wait_200 "${API_URL}/healthz" "${HTTP_RETRIES}" "${HTTP_SLEEP}"
  if [[ "$CHECK_READYZ" == "1" ]]; then
    http_wait_200 "${API_URL}/readyz" "${HTTP_RETRIES}" "${HTTP_SLEEP}"
  fi
  echo
fi

echo "Step 8: Confirm Django DATABASES engine"
"${DC[@]}" exec -T api python -c '
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","k2pweb.settings")
import django; django.setup()
from django.conf import settings
d=settings.DATABASES["default"]
print(d["ENGINE"], d.get("NAME"), d.get("HOST"), d.get("PORT"))
'
echo

if [[ "$START_WORKER" == "1" ]]; then
  echo "Step 9: Start Worker"
  "${DC[@]}" up -d worker
  worker_cid="$(wait_container_running worker 60 1)"
  echo "  worker container: $worker_cid"
  echo "  worker is running"
  echo
fi

if [[ "$CHECK_JOB_RUN" == "1" ]]; then
  run_job_smoke_test
fi

echo "DONE: local stack is up and verified."
echo "Summary:"
"${DC[@]}" ps
