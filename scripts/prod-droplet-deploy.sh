#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.nginx.yml}"

DOMAIN="${DOMAIN:-k2pweb.org}"
BASE_HTTPS_URL="${BASE_HTTPS_URL:-https://${DOMAIN}}"

WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
BUILD="${BUILD:-0}"                 # usually 0 on droplet; set 1 if you rebuild there
START_WORKER="${START_WORKER:-1}"

CURL_INSECURE="${CURL_INSECURE:-0}"
DEPLOY_FAIL_LEVEL="${DEPLOY_FAIL_LEVEL:-WARNING}"  # ERROR|WARNING|INFO

CHECK_STATIC="${CHECK_STATIC:-1}"
K2P_IMAGE="${K2P_IMAGE:-ghcr.io/vitalii-kaplan/knime2py:main}"
CHECK_JOB_RUN="${CHECK_JOB_RUN:-1}"
JOB_FIXTURE_ZIP="${JOB_FIXTURE_ZIP:-tests/data/discounts.zip}"
JOB_WAIT_SECS="${JOB_WAIT_SECS:-180}"

# TLS paths (host)
CERT_DIR_HOST="${CERT_DIR_HOST:-./certs}"
NGINX_CERT_PEM="${NGINX_CERT_PEM:-${CERT_DIR_HOST}/origin.pem}"
NGINX_KEY_PEM="${NGINX_KEY_PEM:-${CERT_DIR_HOST}/origin.key}"

repo_root() { git rev-parse --show-toplevel 2>/dev/null || pwd; }
REPO_ROOT="$(repo_root)"

resolve_compose_file() {
  if [[ -f "$COMPOSE_FILE" ]]; then
    echo "$COMPOSE_FILE"
  elif [[ -f "$REPO_ROOT/$COMPOSE_FILE" ]]; then
    echo "$REPO_ROOT/$COMPOSE_FILE"
  else
    echo "$COMPOSE_FILE"
  fi
}
COMPOSE_FILE="$(resolve_compose_file)"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"; }

trim_ws() {
  local s="${1-}"
  s="${s//$'\r'/}"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

curl_common_flags() { printf '%s\n' "-sS"; }

http_status() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -o /dev/null -w '%{http_code}' "$url" || echo "000"
}

json_get() {
  local js="$1" key="$2"

  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$js" | jq -r --arg k "$key" '.[$k] // ""' 2>/dev/null || true
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$js" | python3 -c 'import sys,json
k=sys.argv[1]
try:
  o=json.load(sys.stdin)
  v=o.get(k,"")
  if v is None: v=""
  sys.stdout.write(str(v))
except Exception:
  pass' "$key" 2>/dev/null || true
    return 0
  fi

  printf '%s' "$js" | tr -d '\r\n' | sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | head -n1 || true
}

wait_for_container_running() {
  local svc="$1" deadline=$((SECONDS + 40)) cid=""
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
  local svc="$1" deadline=$((SECONDS + 90))
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

  local debug secret hosts
  debug="$(awk -F= '$1=="DJANGO_DEBUG"{print $2}' "$env_file" | tail -n1 || true)"
  secret="$(awk -F= '$1=="DJANGO_SECRET_KEY"{print $2}' "$env_file" | tail -n1 || true)"
  hosts="$(awk -F= '$1=="DJANGO_ALLOWED_HOSTS"{print $2}' "$env_file" | tail -n1 || true)"

  debug="$(trim_ws "$debug")"
  secret="$(trim_ws "$secret")"
  hosts="$(trim_ws "$hosts")"

  say ""
  say ".env checks:"
  say "  DJANGO_DEBUG=${debug:-unset}"
  say "  DJANGO_SECRET_KEY=$( [[ -n "${secret:-}" ]] && echo set || echo unset )"
  say "  DJANGO_ALLOWED_HOSTS=${hosts:-unset}"

  [[ "${debug:-}" == "0" ]] || die "DJANGO_DEBUG must be 0 on droplet"
  [[ -n "${secret:-}" ]] || die "DJANGO_SECRET_KEY must be set"
  [[ -n "${hosts:-}" ]] || die "DJANGO_ALLOWED_HOSTS must be set"
  [[ "${hosts}" == *"${DOMAIN}"* ]] || die "DJANGO_ALLOWED_HOSTS must include ${DOMAIN}"

  if git -C "$REPO_ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
    die ".env is tracked by git. Do not commit secrets."
  fi
}

check_tls_material_present() {
  say ""
  say "TLS material checks:"
  [[ -f "$REPO_ROOT/$NGINX_CERT_PEM" ]] || die "missing cert: $REPO_ROOT/$NGINX_CERT_PEM"
  [[ -f "$REPO_ROOT/$NGINX_KEY_PEM" ]] || die "missing key:  $REPO_ROOT/$NGINX_KEY_PEM"
  say "  found $NGINX_CERT_PEM"
  say "  found $NGINX_KEY_PEM"
}

check_ports_published() {
  say ""
  say "Port publish checks (host):"
  if command -v ss >/dev/null 2>&1; then
    ss -lntp | egrep ':(80|443)\b' || die "expected host to be listening on :80 and :443 (nginx publish)."
  else
    dc ps | sed -n '1,120p'
    dc ps | grep -q '0\.0\.0\.0:80->' || die "compose ps doesn't show :80 published"
    dc ps | grep -q '0\.0\.0\.0:443->' || die "compose ps doesn't show :443 published"
  fi
}

check_no_k8s_submit_errors() {
  say ""
  say "Verify worker logs contain no kubectl/openapi errors"
  if dc logs --tail=500 worker 2>/dev/null | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" >/dev/null; then
    dc logs --tail=200 worker | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" || true
    die "Found legacy k8s/kubectl errors in worker logs. Ensure worker uses local Docker runner."
  fi
  say "  OK"
}

check_shared_job_dirs() {
  say ""
  say "Verify shared job directories exist"
  dc exec -T api sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in api container (/data/jobs or /data/results)"
  dc exec -T worker sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in worker container (/data/jobs or /data/results)"
  say "  OK"
}

check_k2p_image_pull() {
  say ""
  say "Verify K2P image is available"
  if ! docker image inspect "$K2P_IMAGE" >/dev/null 2>&1; then
    say "  pulling $K2P_IMAGE ..."
    docker pull "$K2P_IMAGE" || die "failed to pull $K2P_IMAGE (check GHCR auth / network)"
  fi
  say "  OK: image present ($K2P_IMAGE)"
}

check_fixture_contains_workflow() {
  say ""
  say "Verify fixture zip contains workflow.knime"
  local fixture="$REPO_ROOT/$JOB_FIXTURE_ZIP"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"
  if command -v unzip >/dev/null 2>&1; then
    if ! unzip -l "$fixture" | grep -q 'workflow\.knime'; then
      unzip -l "$fixture" | head -n 60 || true
      die "fixture zip does not contain workflow.knime: $fixture"
    fi
    say "  OK"
  else
    say "  WARN: unzip not available; skipping"
  fi
}

run_job_smoke_test() {
  say ""
  say "Job smoke test (upload + result.zip availability)"
  local fixture="$REPO_ROOT/$JOB_FIXTURE_ZIP"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"

  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)

  local job_json job_id status_json status code
  job_json="$(curl "${tls_flag[@]}" $(curl_common_flags) -X POST -F "bundle=@${fixture}" "${BASE_HTTPS_URL}/api/jobs")"
  job_id="$(trim_ws "$(json_get "$job_json" "id")")"
  [[ -n "$job_id" ]] || die "failed to parse job id from response"

  say "  job_id=$job_id"

  local deadline=$((SECONDS + JOB_WAIT_SECS))
  status=""
  while (( SECONDS < deadline )); do
    status_json="$(curl "${tls_flag[@]}" $(curl_common_flags) "${BASE_HTTPS_URL}/api/jobs/$job_id")"
    status="$(trim_ws "$(json_get "$status_json" "status")")"
    [[ "$status" == "SUCCEEDED" ]] && break
    [[ "$status" == "FAILED" ]] && die "job failed: $status_json"
    sleep 1
  done
  [[ "$status" == "SUCCEEDED" ]] || die "job did not finish within ${JOB_WAIT_SECS}s (last=$status)"

  code="$(http_status "${BASE_HTTPS_URL}/api/jobs/$job_id/result.zip")"
  [[ "$code" == "200" ]] || die "result.zip not downloadable (status=$code)"
  say "  OK: result.zip downloadable"
}

main() {
  need_cmd docker
  need_cmd git
  need_cmd curl

  say "Repo: $REPO_ROOT"
  say "Compose file: $COMPOSE_FILE"
  say "DOMAIN: $DOMAIN"
  say "HTTPS: $BASE_HTTPS_URL"
  say "WIPE_VOLUMES=$WIPE_VOLUMES BUILD=$BUILD START_WORKER=$START_WORKER"
  say ""

  check_env_sane
  check_tls_material_present

  say ""
  say "Step 1: Teardown"
  if [[ "$WIPE_VOLUMES" == "1" ]]; then
    dc down -v --remove-orphans
  else
    dc down --remove-orphans
  fi

  if [[ "$BUILD" == "1" ]]; then
    say ""
    say "Step 2: Build images"
    dc build
  fi

  say ""
  say "Step 3: Start Postgres"
  dc up -d postgres
  wait_for_service_healthy postgres
  say "  postgres is healthy"

  say ""
  say "Step 4: Run migrations (one-off)"
  dc run --rm api python manage.py migrate

  say ""
  say "Step 5: Django deploy checks"
  dc run --rm api python manage.py check --deploy --fail-level "$DEPLOY_FAIL_LEVEL"

  if [[ "$CHECK_STATIC" == "1" ]]; then
    say ""
    say "Step 6: Collect static into shared volume"
    dc --profile ops run --rm collectstatic

    say ""
    say "Step 6b: Verify nginx container sees collected static"
    dc up -d nginx >/dev/null
    dc exec -T nginx sh -lc 'test -f /static/ui/app.css && test -f /static/admin/css/base.css' || \
      die "nginx cannot see collected static assets in /static"
  fi

  say ""
  say "Step 7: Start API"
  dc up -d api
  local api_cid
  api_cid="$(wait_for_container_running api || true)"
  [[ -n "$api_cid" ]] || die "api did not reach running state"
  say "  api container: $api_cid"

  say ""
  say "Step 8: Start Nginx"
  dc up -d nginx
  local ngx_cid
  ngx_cid="$(wait_for_container_running nginx || true)"
  [[ -n "$ngx_cid" ]] || die "nginx did not reach running state"
  say "  nginx container: $ngx_cid"

  check_ports_published

  if [[ "$START_WORKER" == "1" ]]; then
    say ""
    say "Step 9: Start Worker"
    dc up -d worker
    local worker_cid
    worker_cid="$(wait_for_container_running worker || true)"
    [[ -n "$worker_cid" ]] || die "worker did not reach running state"
    say "  worker container: $worker_cid"
  fi

  check_no_k8s_submit_errors
  check_shared_job_dirs
  check_k2p_image_pull
  check_fixture_contains_workflow

  if [[ "$CHECK_JOB_RUN" == "1" ]]; then
    run_job_smoke_test
  fi

  say ""
  say "DONE: deploy/start steps passed."
  dc ps
}

main "$@"
