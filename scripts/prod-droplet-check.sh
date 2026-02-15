#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.nginx.yml}"

# On droplet you should test via real domain (Cloudflare)
DOMAIN="${DOMAIN:-k2pweb.org}"
BASE_HTTP_URL="${BASE_HTTP_URL:-http://${DOMAIN}}"
BASE_HTTPS_URL="${BASE_HTTPS_URL:-https://${DOMAIN}}"

WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
BUILD="${BUILD:-0}"                 # usually 0 on droplet; set 1 if you rebuild there
START_WORKER="${START_WORKER:-1}"
CHECK_READYZ="${CHECK_READYZ:-0}"   # legacy switch; keep for compatibility
WAIT_SECS="${WAIT_SECS:-90}"

# NOTE: When hitting Cloudflare edge, -k is NOT required.
# Keep it configurable because some users also run with --resolve to origin IP.
CURL_INSECURE="${CURL_INSECURE:-0}"

DEPLOY_FAIL_LEVEL="${DEPLOY_FAIL_LEVEL:-WARNING}"  # ERROR|WARNING|INFO

CHECK_STATIC="${CHECK_STATIC:-1}"
STATIC_TEST_PATH="${STATIC_TEST_PATH:-/static/admin/css/base.css}"
UI_TEST_PATH="${UI_TEST_PATH:-/static/ui/app.css}"
K2P_IMAGE="${K2P_IMAGE:-ghcr.io/vitalii-kaplan/knime2py:main}"
CHECK_JOB_RUN="${CHECK_JOB_RUN:-1}"
JOB_FIXTURE_ZIP="${JOB_FIXTURE_ZIP:-tests/data/discounts.zip}"
JOB_WAIT_SECS="${JOB_WAIT_SECS:-180}"

# Paths as mounted into nginx container
CERT_DIR_HOST="${CERT_DIR_HOST:-./certs}"
NGINX_CERT_PEM="${NGINX_CERT_PEM:-${CERT_DIR_HOST}/origin.pem}"
NGINX_KEY_PEM="${NGINX_KEY_PEM:-${CERT_DIR_HOST}/origin.key}"

# NEW: /readyz diagnostics controls
DIAG_READYZ="${DIAG_READYZ:-1}"               # print /readyz diagnostics when 1
READYZ_REQUIRED="${READYZ_REQUIRED:-1}"       # when 1, fail if /readyz isn't behaving as expected
READYZ_EXPECT_AUTH="${READYZ_EXPECT_AUTH:-1}" # when 1 and READYZ_REQUIRED=1, require 401/403 on external /readyz

# Basic Auth credentials (optional but recommended for full verification)
# Prefer BASIC_AUTH="user:pass". Alternatively set BASIC_AUTH_USER + BASIC_AUTH_PASS.
BASIC_AUTH="${BASIC_AUTH:-}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-}"
BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-}"

# Optional: origin bypass checks (if you want to isolate Cloudflare)
# ORIGIN_IP="x.x.x.x" enables: curl --resolve DOMAIN:443:ORIGIN_IP ...
ORIGIN_IP="${ORIGIN_IP:-}"

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

has_basic_auth() {
  local user pass
  read -r user pass < <(basic_auth_pair || true)
  [[ -n "${user:-}" && -n "${pass:-}" ]]
}

basic_auth_pair() {
  # prints: "user pass" or empty
  local user="" pass=""
  if [[ -n "${BASIC_AUTH:-}" && "${BASIC_AUTH}" == *:* ]]; then
    user="${BASIC_AUTH%%:*}"
    pass="${BASIC_AUTH#*:}"
  elif [[ -n "${BASIC_AUTH_USER:-}" && -n "${BASIC_AUTH_PASS:-}" ]]; then
    user="${BASIC_AUTH_USER}"
    pass="${BASIC_AUTH_PASS}"
  fi
  user="$(trim_ws "$user")"
  pass="$(trim_ws "$pass")"
  if [[ -n "$user" && -n "$pass" ]]; then
    printf '%s %s\n' "$user" "$pass"
  fi
}

curl_tls_flags() {
  local -a tls=()
  [[ "$CURL_INSECURE" == "1" ]] && tls=(-k)
  printf '%s\n' "${tls[@]+"${tls[@]}"}"
}

curl_common_flags() {
  # Keep output stable: show errors, follow redirects ONLY when explicitly needed.
  # For status probing, we do not use -L by default (redirects are checks by themselves).
  printf '%s\n' "-sS"
}

http_status() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -o /dev/null -w '%{http_code}' "$url" || echo "000"
}

http_status_auth() {
  local url; url="$(trim_ws "${1-}")"
  local user pass
  read -r user pass < <(basic_auth_pair || true)
  [[ -n "${user:-}" && -n "${pass:-}" ]] || { echo "000"; return 0; }

  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -u "${user}:${pass}" -o /dev/null -w '%{http_code}' "$url" || echo "000"
}

http_headers() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -I "$url" 2>/dev/null || true
}

http_body_head() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) "$url" 2>/dev/null | sed -n '1,40p' || true
}

http_body_head_auth() {
  local url; url="$(trim_ws "${1-}")"
  local user pass
  read -r user pass < <(basic_auth_pair || true)
  [[ -n "${user:-}" && -n "${pass:-}" ]] || return 0

  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -u "${user}:${pass}" "$url" 2>/dev/null | sed -n '1,40p' || true
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

assert_protected_endpoint() {
  # Verifies:
  # - Without creds: 401/403 (or 404 if you intentionally hide it)
  # - With creds (if provided): 200 (or another expected code you pass)
  local path="$1"
  local expected_noauth="${2:-401 403}"
  local expected_auth="${3:-200}"

  local url="${BASE_HTTPS_URL}${path}"
  say ""
  say "Protected endpoint check: $path"

  assert_status_in "$url" "$expected_noauth"

  if has_basic_auth; then
    local code
    code="$(http_status_auth "$url")"
    local ok=0
    for s in $expected_auth; do
      [[ "$code" == "$s" ]] && ok=1
    done
    if [[ "$ok" == "1" ]]; then
      say "  AUTH GET $url : $code OK"
    else
      say "  AUTH GET $url : $code (expected [$expected_auth])"
      say "  headers:"
      http_headers "$url" | sed -n '1,40p' || true
      if [[ "$code" == "500" ]]; then
        say "  body (first lines):"
        http_body_head_auth "$url" || true
      fi
      die "Protected endpoint '$path' failed with Basic Auth (status=$code)."
    fi
  else
    say "  NOTE: BASIC_AUTH not set -> skipping authenticated check for $path"
  fi
}

container_upstream_status_from_nginx() {
  # Probe Django upstream from inside nginx container with allowed Host header.
  # usage: container_upstream_status_from_nginx /readyz
  local path="$1"
  dc exec -T nginx sh -lc \
    "curl -sS -o /dev/null -w '%{http_code}' -H 'Host: ${DOMAIN}' -H 'X-Forwarded-Proto: https' http://api:8000${path} || echo 000" \
    2>/dev/null || echo "000"
}

nginx_htpasswd_diagnostics() {
  say ""
  say "nginx htpasswd diagnostics:"

  # File presence/readability
  dc exec -T nginx sh -lc 'ls -l /etc/nginx/.htpasswd 2>/dev/null || true' 2>/dev/null || true
  dc exec -T nginx sh -lc 'test -r /etc/nginx/.htpasswd && echo "  OK: /etc/nginx/.htpasswd is readable" || echo "  FAIL: /etc/nginx/.htpasswd not readable/missing"' 2>/dev/null || true

  # Hash scheme sniff (do not print the hash)
  local firstline hash
  firstline="$(dc exec -T nginx sh -lc 'sed -n "1p" /etc/nginx/.htpasswd 2>/dev/null || true' 2>/dev/null || true)"
  if [[ -n "${firstline:-}" && "${firstline}" == *:* ]]; then
    hash="${firstline#*:}"
    if [[ "$hash" == \$2y\$* || "$hash" == \$2b\$* || "$hash" == \$2a\$* ]]; then
      say "  htpasswd hash scheme: bcrypt"
      # Alpine images frequently lack bcrypt crypt() support; this often leads to 500 on auth.
      local osrel
      osrel="$(dc exec -T nginx sh -lc 'cat /etc/os-release 2>/dev/null || true' 2>/dev/null || true)"
      if echo "$osrel" | grep -qi 'alpine'; then
        say "  WARN: nginx container appears to be Alpine-based; bcrypt htpasswd often fails there."
        say "        If you see 500 on authenticated requests, regenerate htpasswd with MD5 (-m) or use a non-alpine nginx image."
      fi
    elif [[ "$hash" == \$apr1\$* ]]; then
      say "  htpasswd hash scheme: apr1 (MD5) (good compatibility)"
    elif [[ "$hash" == \{SHA\}* ]]; then
      say "  htpasswd hash scheme: SHA1 (base64) (works but weaker)"
    else
      say "  htpasswd hash scheme: unknown (may still be OK)"
    fi
  else
    say "  WARN: could not read /etc/nginx/.htpasswd first line (missing/empty?)"
  fi
}

diagnose_readyz() {
  say ""
  say "Step X: /readyz diagnostics"

  local ext="${BASE_HTTPS_URL}/readyz"
  local ext_code ext_auth_code up_code
  ext_code="$(http_status "$ext")"
  say "  external:  GET $ext : $ext_code"

  if has_basic_auth; then
    ext_auth_code="$(http_status_auth "$ext")"
    say "  external:  AUTH GET $ext : $ext_auth_code"
    if [[ "$ext_auth_code" == "500" ]]; then
      say "  FAIL: authenticated /readyz returns 500 (origin nginx error)."
      say "  headers:"
      http_headers "$ext" | sed -n '1,40p' || true
      say "  body (first lines):"
      http_body_head_auth "$ext" || true
      say ""
      say "  nginx logs tail (look for auth/htpasswd/crypt errors):"
      dc logs --tail=200 nginx 2>/dev/null | sed -n '1,200p' || true
      nginx_htpasswd_diagnostics
      die "authenticated /readyz returned 500"
    fi
  fi

  # Probe upstream from nginx container (bypasses Cloudflare; hits Django directly).
  up_code="$(container_upstream_status_from_nginx /readyz)"
  say "  upstream:   GET http://api:8000/readyz (from nginx container, Host=$DOMAIN) : $up_code"

  say ""
  say "  nginx config excerpt (readyz + auth):"
  dc exec -T nginx sh -lc 'nginx -T 2>/dev/null' | awk '
    /location = \/readyz/ {p=1; print "---- BEGIN location = /readyz ----"}
    p==1 {print}
    p==1 && /^\s*}\s*$/ {print "---- END location = /readyz ----"; exit}
  ' 2>/dev/null || true

  local has_loc has_auth has_user_file
  has_loc="$(dc exec -T nginx sh -lc 'nginx -T 2>/dev/null | grep -F "location = /readyz" >/dev/null && echo 1 || echo 0' 2>/dev/null || echo 0)"
  has_auth="$(dc exec -T nginx sh -lc 'nginx -T 2>/dev/null | awk "/location = \\/readyz/{p=1} p && /auth_basic\\s+/{found=1} p && /^\s*}\s*$/{exit} END{print (found?1:0)}"' 2>/dev/null || echo 0)"
  has_user_file="$(dc exec -T nginx sh -lc 'nginx -T 2>/dev/null | awk "/location = \\/readyz/{p=1} p && /auth_basic_user_file\\s+/{found=1} p && /^\s*}\s*$/{exit} END{print (found?1:0)}"' 2>/dev/null || echo 0)"

  if [[ "$has_loc" == "1" && ( "$has_auth" == "0" || "$has_user_file" == "0" ) ]]; then
    say ""
    say "  WARN: nginx has location = /readyz but missing auth_basic and/or auth_basic_user_file."
    say "        If /readyz is internal, add both directives to that location."
  fi

  say ""
  if [[ "$up_code" == "404" ]]; then
    say "  verdict: Django does NOT expose /readyz (upstream 404). Fix Django routing, not nginx/Cloudflare."
  elif [[ "$up_code" == "400" ]]; then
    say "  verdict: Django upstream returns 400. This is typically Host/ALLOWED_HOSTS mismatch."
    say "           Ensure upstream probe includes: -H 'Host: ${DOMAIN}'. Script already does."
  elif [[ "$up_code" == "200" && ( "$ext_code" == "401" || "$ext_code" == "403" ) ]]; then
    say "  verdict: /readyz exists and is protected externally (expected)."
  elif [[ "$up_code" == "200" && "$ext_code" == "200" ]]; then
    say "  verdict: /readyz exists and is publicly accessible (not expected if you intend to hide internals)."
  else
    say "  verdict: mixed signals. Inspect nginx -T excerpt above and Django routing."
  fi

  if [[ "$READYZ_REQUIRED" == "1" ]]; then
    # Enforce upstream existence
    [[ "$up_code" != "404" ]] || die "/readyz is required, but Django upstream returns 404 (endpoint missing)."

    # Enforce external policy
    if [[ "$READYZ_EXPECT_AUTH" == "1" ]]; then
      if [[ "$ext_code" != "401" && "$ext_code" != "403" ]]; then
        die "/readyz must be auth-protected externally, expected 401/403 but got $ext_code."
      fi
      if has_basic_auth; then
        ext_auth_code="$(http_status_auth "$ext")"
        [[ "$ext_auth_code" == "200" ]] || die "/readyz auth check expected 200 but got $ext_auth_code."
      else
        say "  NOTE: READYZ is required and expected to be protected, but BASIC_AUTH not set -> cannot verify auth success (200)."
      fi
    else
      [[ "$ext_code" == "200" ]] || die "/readyz must be public externally, expected 200 but got $ext_code."
    fi
  fi
}

json_get() {
  # json_get "<json>" "<key>"
  # tries python3, jq, fallback sed (best-effort)
  local js="$1" key="$2"
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$js" | python3 - "$key" <<'PY'
import sys, json
key = sys.argv[1]
try:
  obj = json.load(sys.stdin)
  v = obj.get(key, "")
  if v is None: v = ""
  print(v)
except Exception:
  print("")
PY
    return 0
  fi

  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$js" | jq -r --arg k "$key" '.[$k] // ""' 2>/dev/null || true
    return 0
  fi

  # fallback: naive
  printf '%s' "$js" | sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | head -n1 || true
}

run_job_smoke_test() {
  say ""
  say "Step 18: Job smoke test (upload + result.zip availability)"
  local fixture="$REPO_ROOT/$JOB_FIXTURE_ZIP"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"

  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)

  local job_json job_id status code
  job_json="$(curl "${tls_flag[@]}" $(curl_common_flags) -X POST -F "bundle=@${fixture}" "${BASE_HTTPS_URL}/api/jobs")"
  job_id="$(json_get "$job_json" "id")"
  [[ -n "$job_id" ]] || die "failed to parse job id from response: $job_json"
  say "  job_id=$job_id"

  local deadline=$((SECONDS + JOB_WAIT_SECS))
  status=""
  while (( SECONDS < deadline )); do
    status="$(curl "${tls_flag[@]}" $(curl_common_flags) "${BASE_HTTPS_URL}/api/jobs/$job_id" | python3 - <<'PY' 2>/dev/null || true
import sys, json
try:
  obj=json.load(sys.stdin)
  print(obj.get("status",""))
except Exception:
  print("")
PY
)"
    status="$(trim_ws "$status")"
    if [[ "$status" == "SUCCEEDED" ]]; then
      break
    fi
    if [[ "$status" == "FAILED" ]]; then
      local resp
      resp="$(curl "${tls_flag[@]}" $(curl_common_flags) "${BASE_HTTPS_URL}/api/jobs/$job_id")"
      die "job failed. Full response: $resp"
    fi
    sleep 1
  done

  [[ "$status" == "SUCCEEDED" ]] || die "job did not finish within ${JOB_WAIT_SECS}s (last=$status)"
  code="$(http_status "${BASE_HTTPS_URL}/api/jobs/$job_id/result.zip")"
  [[ "$code" == "200" ]] || die "result.zip not downloadable (status=$code)"
  say "  GET /api/jobs/$job_id/result.zip : 200 OK"
}

check_no_k8s_submit_errors() {
  say ""
  say "Step 14: Verify worker logs contain no kubectl/openapi errors"
  if dc logs --tail=500 worker 2>/dev/null | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" >/dev/null; then
    dc logs --tail=200 worker | grep -E "openapi/v2|localhost:8080|k8s_submit_failed|kubectl" || true
    die "Found legacy k8s/kubectl errors in worker logs. Ensure worker uses local Docker runner."
  fi
  say "  OK: no k8s/kubectl errors in worker logs"
}

check_shared_job_dirs() {
  say ""
  say "Step 15: Verify shared job directories exist"
  dc exec -T api sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in api container (/data/jobs or /data/results)"
  dc exec -T worker sh -lc 'test -d /data/jobs && test -d /data/results' || \
    die "shared job dirs missing in worker container (/data/jobs or /data/results)"
  say "  OK: /data/jobs and /data/results present in api + worker"
}

check_k2p_image_pull() {
  say ""
  say "Step 16: Verify K2P image is available"
  if ! docker image inspect "$K2P_IMAGE" >/dev/null 2>&1; then
    say "  pulling $K2P_IMAGE ..."
    docker pull "$K2P_IMAGE" || die "failed to pull $K2P_IMAGE (check GHCR auth / network)"
  fi
  say "  OK: image present ($K2P_IMAGE)"
}

check_fixture_contains_workflow() {
  say ""
  say "Step 17: Verify fixture zip contains workflow.knime"
  local fixture="$REPO_ROOT/$JOB_FIXTURE_ZIP"
  [[ -f "$fixture" ]] || die "missing job fixture: $fixture"
  if command -v unzip >/dev/null 2>&1; then
    if ! unzip -l "$fixture" | grep -q 'workflow\.knime'; then
      say "  DEBUG: zip listing (first 50 lines):"
      unzip -l "$fixture" | head -n 50 || true
      say "  DEBUG: workflow.knime matches:"
      unzip -l "$fixture" | grep -E 'workflow\.knime' || true
      die "fixture zip does not contain workflow.knime: $fixture"
    fi
    say "  OK: workflow.knime found in fixture"
  else
    say "  WARN: unzip not available; cannot verify workflow.knime in fixture"
  fi
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

check_origin_bypass_if_configured() {
  [[ -n "${ORIGIN_IP:-}" ]] || return 0
  say ""
  say "Origin bypass checks (optional): ORIGIN_IP=$ORIGIN_IP"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)

  # This bypasses Cloudflare and hits droplet directly, using SNI+Host for DOMAIN.
  local url="https://${DOMAIN}/healthz"
  local code
  code="$(curl "${tls_flag[@]}" $(curl_common_flags) --resolve "${DOMAIN}:443:${ORIGIN_IP}" -o /dev/null -w '%{http_code}' "$url" || echo 000)"
  say "  --resolve ${DOMAIN}:443:${ORIGIN_IP} GET /healthz : $code"
  [[ "$code" == "200" ]] || die "origin bypass /healthz expected 200, got $code"
}

main() {
  need_cmd docker
  need_cmd git
  need
