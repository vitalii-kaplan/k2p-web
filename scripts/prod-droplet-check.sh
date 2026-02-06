#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.nginx.yml}"

# On droplet you should test via real domain (Cloudflare)
DOMAIN="${DOMAIN:-k2pweb.org}"
BASE_HTTP_URL="${BASE_HTTP_URL:-http://${DOMAIN}}"
BASE_HTTPS_URL="${BASE_HTTPS_URL:-https://${DOMAIN}}"

WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
BUILD="${BUILD:-0}"                 # usually 0 on droplet if you pull code already; set 1 if you rebuild there
START_WORKER="${START_WORKER:-1}"
CHECK_READYZ="${CHECK_READYZ:-1}"
WAIT_SECS="${WAIT_SECS:-90}"

# If you use Cloudflare Origin cert, curl will not trust it by default -> -k needed for direct https to domain.
# If you later switch to a publicly trusted cert (Let's Encrypt), set CURL_INSECURE=0.
CURL_INSECURE="${CURL_INSECURE:-1}"

DEPLOY_FAIL_LEVEL="${DEPLOY_FAIL_LEVEL:-WARNING}"  # ERROR|WARNING|INFO

CHECK_STATIC="${CHECK_STATIC:-1}"
STATIC_TEST_PATH="${STATIC_TEST_PATH:-/static/admin/css/base.css}"
UI_TEST_PATH="${UI_TEST_PATH:-/static/ui/app.css}"

# Paths as mounted into nginx container
CERT_DIR_HOST="${CERT_DIR_HOST:-./certs}"
NGINX_CERT_PEM="${NGINX_CERT_PEM:-${CERT_DIR_HOST}/origin.pem}"
NGINX_KEY_PEM="${NGINX_KEY_PEM:-${CERT_DIR_HOST}/origin.key}"

# -----------------------------------------------------------------------------

repo_root() { git rev-parse --show-toplevel 2>/dev/null || pwd; }
REPO_ROOT="$(repo_root)"

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

http_status() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" -sS -o /dev/null -w '%{http_code}' "$url" || echo "000"
}

http_headers() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" -sS -I "$url" 2>/dev/null || true
}

wait_http_status_in() {
  local url="$1" expected="$2" deadline code
  deadline=$((SECONDS + WAIT_SECS))
  while (( SECONDS < deadline )); do
    code="$(http_status "$url")"
    for s in $expected; do
      [[ "$code" == "$s" ]] && return 0
    done
    sleep 1
  done
  say "  last status for $url: $code"
  http_headers "$url" | sed -n '1,40p' || true
  return 1
}

assert_status_in() {
  local url="$1" expected="$2" code
  code="$(http_status "$url")"
  for s in $expected; do
    if [[ "$code" == "$s" ]]; then
      say "  GET $url : $code OK"
      return 0
    fi
  done
  die "GET $url expected one of [$expected], got $code"
}

check_no_k8s_submit_errors() {
  say ""
  say "Step 14: Verify worker logs contain no kubectl/openapi errors"
  # Look for kubectl/openapi localhost:8080 error signature
  if dc logs --tail=500 worker 2>/dev/null | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" >/dev/null; then
    dc logs --tail=200 worker | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" || true
    die "Found legacy k8s/kubectl errors in worker logs. Ensure worker uses local Docker runner."
  fi
  say "  OK: no k8s/kubectl errors in worker logs"
}

check_shared_job_dirs() {
  say ""
  say "Step 14b: Verify shared job directories exist"
  dc exec -T api sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in api container (/data/jobs or /data/results)"
  dc exec -T worker sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in worker container (/data/jobs or /data/results)"
  say "  OK: /data/jobs and /data/results present in api + worker"
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

  # Minimal sanity checks; droplet compose sets DB vars via environment, so we focus on critical Django flags.
  local debug secret hosts ssl_redirect xfp
  debug="$(awk -F= '$1=="DJANGO_DEBUG"{print $2}' "$env_file" | tail -n1 || true)"
  secret="$(awk -F= '$1=="DJANGO_SECRET_KEY"{print $2}' "$env_file" | tail -n1 || true)"
  hosts="$(awk -F= '$1=="DJANGO_ALLOWED_HOSTS"{print $2}' "$env_file" | tail -n1 || true)"
  ssl_redirect="$(awk -F= '$1=="SECURE_SSL_REDIRECT"{print $2}' "$env_file" | tail -n1 || true)"
  xfp="$(awk -F= '$1=="USE_X_FORWARDED_PROTO"{print $2}' "$env_file" | tail -n1 || true)"

  debug="$(trim_ws "$debug")"
  secret="$(trim_ws "$secret")"
  hosts="$(trim_ws "$hosts")"
  ssl_redirect="$(trim_ws "$ssl_redirect")"
  xfp="$(trim_ws "$xfp")"

  say ""
  say ".env checks:"
  say "  DJANGO_DEBUG=${debug:-unset}"
  say "  DJANGO_SECRET_KEY=$( [[ -n "${secret:-}" ]] && echo set || echo unset )"
  say "  DJANGO_ALLOWED_HOSTS=${hosts:-unset}"
  say "  USE_X_FORWARDED_PROTO=${xfp:-unset}"
  say "  SECURE_SSL_REDIRECT=${ssl_redirect:-unset}"

  [[ "${debug:-}" == "0" ]] || die "DJANGO_DEBUG must be 0 on droplet"
  [[ -n "${secret:-}" ]] || die "DJANGO_SECRET_KEY must be set"
  [[ -n "${hosts:-}" ]] || die "DJANGO_ALLOWED_HOSTS must be set"
  [[ "${hosts}" == *"${DOMAIN}"* ]] || die "DJANGO_ALLOWED_HOSTS must include ${DOMAIN}"

  if git -C "$REPO_ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
    die ".env is tracked by git. Do not commit secrets."
  fi
}

check_tls_material_present() {
  # Only check if nginx actually maps 443 (almost certainly in your prod file)
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
  # Use ss if available; fallback to docker compose ps.
  if command -v ss >/dev/null 2>&1; then
    ss -lntp | egrep ':(80|443)\b' || die "expected host to be listening on :80 and :443 (nginx publish)."
  else
    dc ps | sed -n '1,120p'
    dc ps | grep -q '0\.0\.0\.0:80->' || die "compose ps doesn't show :80 published"
    dc ps | grep -q '0\.0\.0\.0:443->' || die "compose ps doesn't show :443 published"
  fi
}

main() {
  need_cmd docker
  need_cmd git
  need_cmd curl

  DOMAIN="$(trim_ws "$DOMAIN")"
  BASE_HTTP_URL="$(trim_ws "$BASE_HTTP_URL")"
  BASE_HTTPS_URL="$(trim_ws "$BASE_HTTPS_URL")"

  say "Repo: $REPO_ROOT"
  say "Docker context: $(docker context show 2>/dev/null || echo unknown)"
  say "Compose file: $COMPOSE_FILE"
  say "DOMAIN: $DOMAIN"
  say "HTTP:  $BASE_HTTP_URL"
  say "HTTPS: $BASE_HTTPS_URL"
  say "WIPE_VOLUMES=$WIPE_VOLUMES BUILD=$BUILD START_WORKER=$START_WORKER CHECK_READYZ=$CHECK_READYZ CURL_INSECURE=$CURL_INSECURE"
  say ""

  check_env_sane
  check_tls_material_present

  say ""
  say "Step 1: Teardown"
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
    say "Step 6: Collect static into shared volume (collectstatic service)"
    # Use your dedicated service (profile ops); avoids relying on api container state.
    dc --profile ops run --rm collectstatic

    say ""
    say "Step 6b: Verify nginx container sees /static/ui assets"
    dc up -d nginx >/dev/null
    dc exec -T nginx sh -lc 'test -f /static/ui/app.css && test -f /static/admin/css/base.css' || \
      die "nginx cannot see collected static assets in /static (volume mount / collectstatic issue)."
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

  say ""
  say "Step 9: HTTP->HTTPS redirect checks"
  # Expect redirect on http paths when SECURE_SSL_REDIRECT=1 (or nginx redirects).
  wait_http_status_in "$BASE_HTTP_URL/healthz" "301 302 308" || die "expected HTTP redirect for /healthz"
  say "  GET $BASE_HTTP_URL/healthz : redirect OK"
  if [[ "$CHECK_READYZ" == "1" ]]; then
    wait_http_status_in "$BASE_HTTP_URL/readyz" "301 302 308" || die "expected HTTP redirect for /readyz"
    say "  GET $BASE_HTTP_URL/readyz : redirect OK"
  fi

  say ""
  say "Step 10: HTTPS readiness"
  wait_http_status_in "$BASE_HTTPS_URL/healthz" "200" || die "GET $BASE_HTTPS_URL/healthz did not become 200"
  say "  GET $BASE_HTTPS_URL/healthz : 200 OK"
  if [[ "$CHECK_READYZ" == "1" ]]; then
    wait_http_status_in "$BASE_HTTPS_URL/readyz" "200" || die "GET $BASE_HTTPS_URL/readyz did not become 200"
    say "  GET $BASE_HTTPS_URL/readyz : 200 OK"
  fi

  say ""
  say "Step 11: Access-control checks (through domain)"
  assert_status_in "$BASE_HTTPS_URL/admin/sql/" "404"
  assert_status_in "$BASE_HTTPS_URL/admin/" "401 403"
  assert_status_in "$BASE_HTTPS_URL/metrics" "401 403"

  if [[ "$CHECK_STATIC" == "1" ]]; then
    say ""
    say "Step 12: Static serving checks (through domain)"
    assert_status_in "$BASE_HTTPS_URL$STATIC_TEST_PATH" "200"
    assert_status_in "$BASE_HTTPS_URL$UI_TEST_PATH" "200"
  fi

  if [[ "$START_WORKER" == "1" ]]; then
    say ""
    say "Step 13: Start Worker"
    dc up -d worker
    local worker_cid
    worker_cid="$(wait_for_container_running worker || true)"
    [[ -n "$worker_cid" ]] || die "worker did not reach running state"
    say "  worker container: $worker_cid"
  fi

  check_no_k8s_submit_errors
  check_shared_job_dirs

  say ""
  say "DONE: droplet deploy checks passed."
  say "Summary:"
  dc ps
}

main "$@"
