#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.nginx.yml}"
API_URL="${API_URL:-https://127.0.0.1}"   # hits nginx
WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
START_WORKER="${START_WORKER:-0}"
CHECK_READYZ="${CHECK_READYZ:-1}"
REQUIRE_TLS="${REQUIRE_TLS:-1}"
BUILD="${BUILD:-1}"
WAIT_SECS="${WAIT_SECS:-60}"
CURL_INSECURE="${CURL_INSECURE:-1}"  # 1 => curl -k for local/self-signed certs

DEPLOY_FAIL_LEVEL="${DEPLOY_FAIL_LEVEL:-WARNING}"  # ERROR|WARNING|INFO
CHECK_STATIC="${CHECK_STATIC:-1}"
STATIC_TEST_PATH="${STATIC_TEST_PATH:-/static/admin/css/base.css}"
CHECK_JOB_RUN="${CHECK_JOB_RUN:-1}"
JOB_FIXTURE_ZIP="${JOB_FIXTURE_ZIP:-tests/data/discounts.zip}"
JOB_WAIT_SECS="${JOB_WAIT_SECS:-120}"
FORCE_JOB_RUN="${FORCE_JOB_RUN:-0}"

repo_root() { git rev-parse --show-toplevel 2>/dev/null || pwd; }
REPO_ROOT="$(repo_root)"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"; }

mask_secret() { [[ -n "${1:-}" ]] && echo "set" || echo "unset"; }

trim_ws() {
  # trim leading/trailing whitespace and strip CR
  local s="${1-}"
  s="${s//$'\r'/}"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

get_env_value() {
  local key="$1" file="$2"
  [[ -f "$file" ]] || return 1
  awk -F= -v k="$key" '
    $0 ~ "^[[:space:]]*#" {next}
    $0 ~ "^[[:space:]]*$" {next}
    $1==k {print $2; exit 0}
  ' "$file"
}

url_host() {
  local u="$1"
  u="${u#*://}"
  u="${u%%/*}"
  u="${u%%:*}"
  echo "$u"
}

# Global (always set)
CURL_HOST_HEADER=""
DJANGO_ALLOWED_HOSTS_RAW=""

setup_mac_jobdata_bind() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi

  # Bind /data to a host-shared path so the worker can mount it via docker.sock.
  # Repo root is shared by Docker Desktop by default.
  local host_root="$REPO_ROOT/var"
  mkdir -p "$host_root/jobs" "$host_root/results"

  export JOBDATA_HOST_PATH="$host_root"
  export HOST_JOB_STORAGE_ROOT="$host_root/jobs"
  export HOST_RESULT_STORAGE_ROOT="$host_root/results"
  say "  mac bind: JOBDATA_HOST_PATH=$JOBDATA_HOST_PATH"
}

setup_curl_host_header() {
  local api_host hosts first
  api_host="$(url_host "$API_URL")"
  hosts="${DJANGO_ALLOWED_HOSTS_RAW:-}"

  CURL_HOST_HEADER=""

  # Only needed when we hit localhost but ALLOWED_HOSTS is domain-only
  if [[ "$api_host" == "127.0.0.1" || "$api_host" == "localhost" ]]; then
    if [[ -n "$hosts" ]] && [[ "$hosts" != *"127.0.0.1"* ]] && [[ "$hosts" != *"localhost"* ]]; then
      first="${hosts%%,*}"
      first="$(trim_ws "$first")"
      first="${first//[[:space:]]/}"
      first="${first//$'\r'/}"
      [[ -n "$first" ]] && CURL_HOST_HEADER="Host: $first"
    fi
  fi
}

http_status() {
  local url
  url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  if [[ -n "$CURL_HOST_HEADER" ]]; then
    curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" -o /dev/null -w '%{http_code}' "$url" || echo "000"
  else
    curl "${tls_flag[@]}" -sS -o /dev/null -w '%{http_code}' "$url" || echo "000"
  fi
}

assert_status_in() {
  local url="$1"
  local expected="$2"  # space-separated list, e.g. "401 403"
  local code
  code="$(http_status "$url")"
  for s in $expected; do
    if [[ "$code" == "$s" ]]; then
      say "  GET $url : $code OK"
      return 0
    fi
  done
  die "GET $url expected one of [$expected], got $code"
}

run_job_smoke_test() {
  say ""
  say "Step 14: Job smoke test (upload + result.zip availability)"
  local fixture="$REPO_ROOT/$JOB_FIXTURE_ZIP"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"

  local job_json job_id status code
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  if [[ -n "$CURL_HOST_HEADER" ]]; then
    job_json="$(curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" -X POST -F "bundle=@${fixture}" "$API_URL/api/jobs")"
  else
    job_json="$(curl "${tls_flag[@]}" -sS -X POST -F "bundle=@${fixture}" "$API_URL/api/jobs")"
  fi
  job_id="$(echo "$job_json" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$job_id" ]] || die "failed to parse job id from response: $job_json"
  say "  job_id=$job_id"

  local deadline=$((SECONDS + JOB_WAIT_SECS))
  status=""
  while (( SECONDS < deadline )); do
    if [[ -n "$CURL_HOST_HEADER" ]]; then
      status="$(curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" "$API_URL/api/jobs/$job_id" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    else
      status="$(curl "${tls_flag[@]}" -sS "$API_URL/api/jobs/$job_id" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    fi
    if [[ "$status" == "SUCCEEDED" ]]; then
      break
    fi
    if [[ "$status" == "FAILED" ]]; then
      local err
      if [[ -n "$CURL_HOST_HEADER" ]]; then
        err="$(curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" "$API_URL/api/jobs/$job_id" | sed -n 's/.*"error_message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
      else
        err="$(curl "${tls_flag[@]}" -sS "$API_URL/api/jobs/$job_id" | sed -n 's/.*"error_message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
      fi
      die "job failed: $err"
    fi
    sleep 1
  done

  [[ "$status" == "SUCCEEDED" ]] || die "job did not finish within ${JOB_WAIT_SECS}s (last=$status)"
  code="$(http_status "$API_URL/api/jobs/$job_id/result.zip")"
  [[ "$code" == "200" ]] || die "result.zip not downloadable (status=$code)"
  say "  GET /api/jobs/$job_id/result.zip : 200 OK"
}

wait_http_200() {
  local url deadline code
  url="$(trim_ws "${1-}")"
  deadline=$((SECONDS + WAIT_SECS))
  code="000"

  while (( SECONDS < deadline )); do
    code="$(http_status "$url")"
    [[ "$code" == "200" ]] && return 0
    sleep 1
  done

  say "  last status for $url: $code"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  if [[ -n "$CURL_HOST_HEADER" ]]; then
    curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" -D- -o /dev/null "$url" || true
  else
    curl "${tls_flag[@]}" -sS -D- -o /dev/null "$url" || true
  fi
  return 1
}

wait_for_container_running() {
  local svc="$1" deadline=$((SECONDS + 30)) cid=""
  while (( SECONDS < deadline )); do
    cid="$(dc ps -q "$svc" 2>/dev/null || true)"
    if [[ -n "$cid" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)" == "true" ]]; then
      echo "$cid"; return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_service_healthy() {
  local svc="$1" deadline=$((SECONDS + 60))
  local cid; cid="$(dc ps -q "$svc" 2>/dev/null || true)"
  [[ -n "$cid" ]] || die "no container id for service '$svc' (not started?)"

  while (( SECONDS < deadline )); do
    local health
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo "unknown")"
    [[ "$health" == "healthy" ]] && return 0
    [[ "$health" == "unhealthy" ]] && { dc logs --tail=200 "$svc" || true; die "service '$svc' is unhealthy"; }
    sleep 1
  done

  dc logs --tail=200 "$svc" || true
  die "timeout waiting for '$svc' to become healthy"
}

check_env_sane() {
  local env_file="$REPO_ROOT/.env"
  [[ -f "$env_file" ]] || die "missing .env at repo root: $env_file"

  local debug db_engine secret hosts
  debug="$(get_env_value DJANGO_DEBUG "$env_file" || true)"
  db_engine="$(get_env_value DB_ENGINE "$env_file" || true)"
  secret="$(get_env_value DJANGO_SECRET_KEY "$env_file" || true)"
  hosts="$(get_env_value DJANGO_ALLOWED_HOSTS "$env_file" || true)"

  debug="$(trim_ws "$debug")"
  db_engine="$(trim_ws "$db_engine")"
  secret="$(trim_ws "$secret")"
  hosts="$(trim_ws "$hosts")"

  DJANGO_ALLOWED_HOSTS_RAW="${hosts:-}"

  say ""
  say ".env checks:"
  say "  DJANGO_DEBUG=${debug:-unset}"
  say "  DB_ENGINE=${db_engine:-unset}"
  say "  DJANGO_SECRET_KEY=$(mask_secret "$secret")"

  [[ "${debug:-}" == "0" ]] || die "DJANGO_DEBUG must be 0"
  [[ "${db_engine:-}" == "postgres" ]] || die "DB_ENGINE must be postgres"
  [[ -n "${secret:-}" ]] || die "DJANGO_SECRET_KEY must be set"
  [[ "${secret:-}" != "dev-only-change-me" ]] || die "DJANGO_SECRET_KEY is still dev-only-change-me"

  if [[ "${hosts:-}" == "127.0.0.1,localhost" || "${hosts:-}" == "localhost,127.0.0.1" ]]; then
    say "  WARN: DJANGO_ALLOWED_HOSTS is still localhost-only. For real production, set your domain(s)."
  fi

  if git -C "$REPO_ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
    die ".env is tracked by git. Do not commit secrets. Add .env to .gitignore and rotate secrets."
  fi
}

check_nginx_is_front() {
  # Must have nginx service
  if ! dc config | grep -qE '^[[:space:]]*nginx:'; then
    die "compose file does not define 'nginx' service"
  fi
  [[ -f "$REPO_ROOT/deploy/nginx/nginx.conf" ]] || die "missing deploy/nginx/nginx.conf"
  [[ -f "$REPO_ROOT/deploy/nginx/.htpasswd" ]] || die "missing deploy/nginx/.htpasswd"
}

check_server_header_is_nginx() {
  local url hdr
  url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  if [[ -n "$CURL_HOST_HEADER" ]]; then
    hdr="$(curl "${tls_flag[@]}" -sS -H "$CURL_HOST_HEADER" -I "$url" 2>/dev/null || true)"
  else
    hdr="$(curl "${tls_flag[@]}" -sS -I "$url" 2>/dev/null || true)"
  fi

  if ! echo "$hdr" | grep -qiE '^Server: *nginx'; then
    say "  headers:"
    echo "$hdr" | sed -n '1,40p'
    die "expected Server: nginx (requests must go through nginx)"
  fi
}

main() {
  need_cmd docker
  need_cmd git
  need_cmd curl

  API_URL="$(trim_ws "$API_URL")"

  say "Repo: $REPO_ROOT"
  say "Docker context: $(docker context show 2>/dev/null || echo unknown)"
  say "Compose file: $COMPOSE_FILE"
  say "API_URL: $API_URL"
  say "WIPE_VOLUMES=$WIPE_VOLUMES START_WORKER=$START_WORKER CHECK_READYZ=$CHECK_READYZ REQUIRE_TLS=$REQUIRE_TLS BUILD=$BUILD CURL_INSECURE=$CURL_INSECURE"
  say ""

  [[ "$REQUIRE_TLS" == "0" || "$API_URL" == https://* ]] || die "REQUIRE_TLS=1 but API_URL is not https://"

  check_env_sane
  setup_mac_jobdata_bind
  setup_curl_host_header
  check_nginx_is_front

  if [[ -n "$CURL_HOST_HEADER" ]]; then
    say "  NOTE: sending -H '$CURL_HOST_HEADER' (to satisfy DJANGO_ALLOWED_HOSTS when hitting localhost)"
  fi

  say ""
  say "Step 1: Teardown"
  # Remove named containers if left behind from non-compose runs.
  for c in k2pweb-api k2pweb-worker k2pweb-postgres k2pweb-nginx; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
      docker rm -f "$c" >/dev/null 2>&1 || true
    fi
  done
  if [[ "$WIPE_VOLUMES" == "1" ]]; then
    say "  Running: docker compose down -v --remove-orphans"
    dc down -v --remove-orphans
  else
    say "  Running: docker compose down --remove-orphans"
    dc down --remove-orphans
  fi

  if [[ "$BUILD" == "1" ]]; then
    say ""
    say "Step 2: Build images"
    dc build
  fi

  say ""
  say "Step 3: Verify python runtime deps (gunicorn, django)"
  dc run --rm api sh -lc '
    set -e
    python -c "import django; print(\"django:\", django.get_version())"
    python -c "import gunicorn; print(\"gunicorn:\", gunicorn.__version__)"
  '

  say ""
  say "Step 4: Start Postgres"
  dc up -d postgres
  wait_for_service_healthy postgres
  say "  postgres is healthy"

  say ""
  say "Step 5: Run migrations (one-off)"
  dc run --rm api python manage.py migrate

  say ""
  say "Step 6: Django deploy checks"
  dc run --rm api python manage.py check --deploy --fail-level "$DEPLOY_FAIL_LEVEL"

  if [[ "$CHECK_STATIC" == "1" ]]; then
    say ""
    say "Step 7: Collect static into shared volume (/static)"
    dc run --rm api python manage.py collectstatic --noinput

    # Hard check: file must exist inside the shared volume
    dc run --rm api sh -lc 'test -f /static/admin/css/base.css' || \
      die "collectstatic did not produce /static/admin/css/base.css. Ensure STATIC_ROOT=/static is used in settings."
  fi

  say ""
  say "Step 8: Start API (internal)"
  dc up -d api
  local api_cid
  api_cid="$(wait_for_container_running api || true)"
  [[ -n "$api_cid" ]] || die "api did not reach running state"
  say "  api container: $api_cid"

  say ""
  say "Step 9: Start Nginx (public entrypoint)"
  dc up -d nginx
  local ngx_cid
  ngx_cid="$(wait_for_container_running nginx || true)"
  [[ -n "$ngx_cid" ]] || die "nginx did not reach running state"
  say "  nginx container: $ngx_cid"

  say ""
  say "Step 10: HTTP readiness (through nginx)"
  wait_http_200 "$API_URL/healthz" || die "GET $API_URL/healthz did not become 200"
  say "  GET $API_URL/healthz : 200 OK"
  if [[ "$CHECK_READYZ" == "1" ]]; then
    wait_http_200 "$API_URL/readyz" || die "GET $API_URL/readyz did not become 200"
    say "  GET $API_URL/readyz : 200 OK"
  fi

  check_server_header_is_nginx "$API_URL/healthz"
  say "  OK: Server header is nginx"

  say ""
  say "Step 11: Access-control checks"
  assert_status_in "$API_URL/admin/sql/" "404"
  assert_status_in "$API_URL/admin/" "401 403"
  assert_status_in "$API_URL/metrics" "401 403"

  if [[ "$CHECK_STATIC" == "1" ]]; then
    say ""
    say "Step 12: Static serving check (nginx /static/)"
    local st="$API_URL$STATIC_TEST_PATH"
    local code
    code="$(http_status "$st")"
    [[ "$code" == "200" ]] || die "static check failed: GET $st expected 200, got $code"
    say "  GET $st : 200 OK"
  fi

  # UI static check (app.css)
  local ui="$API_URL/static/ui/app.css"
  local ui_code
  ui_code="$(http_status "$ui")"
  [[ "$ui_code" == "200" ]] || die "UI static check failed: GET $ui expected 200, got $ui_code"
  say "  GET $ui : 200 OK"

  if [[ "$START_WORKER" == "1" ]]; then
    say ""
    say "Step 13: Start Worker"
    dc up -d worker
    local worker_cid
    worker_cid="$(wait_for_container_running worker || true)"
    [[ -n "$worker_cid" ]] || die "worker did not reach running state"
    say "  worker container: $worker_cid"
    if [[ "$(uname -s)" == "Darwin" ]]; then
      local src
      src="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$worker_cid" 2>/dev/null || true)"
      local norm_src="$src"
      if [[ "$norm_src" == /host_mnt/* ]]; then
        norm_src="${norm_src#/host_mnt}"
      fi
      if [[ -z "$src" || "$norm_src" != "$JOBDATA_HOST_PATH" ]]; then
        die "worker /data is not bound to host path. Expected $JOBDATA_HOST_PATH, got '${src:-none}'."
      fi
    fi
  fi

  if [[ "$CHECK_JOB_RUN" == "1" ]]; then
    run_job_smoke_test
  fi

  say ""
  say "DONE: production (nginx front) checks passed."
  say "Summary:"
  dc ps
}

main "$@"
