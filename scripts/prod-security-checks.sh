#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.nginx.yml}"

DOMAIN="${DOMAIN:-k2pweb.org}"
BASE_HTTP_URL="${BASE_HTTP_URL:-http://${DOMAIN}}"
BASE_HTTPS_URL="${BASE_HTTPS_URL:-https://${DOMAIN}}"

WAIT_SECS="${WAIT_SECS:-30}"
CURL_INSECURE="${CURL_INSECURE:-0}"

LOG_TAIL="${LOG_TAIL:-200}"

# Explicit protected paths (no nginx -T parsing).
# Keep this list in sync with deploy/nginx/nginx.conf.
PROTECTED_PATHS_DEFAULT=(
  "/readyz"
  "/admin/sql/"
  "/admin/"
  "/metrics"
  "/api/schema/"
)

# Optional: override list from env, space-separated:
#   PROTECTED_PATHS="/readyz /admin/ /metrics"
PROTECTED_PATHS_ENV="${PROTECTED_PATHS:-}"

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

http_headers() {
  local url; url="$(trim_ws "${1-}")"
  local tls_flag=()
  [[ "$CURL_INSECURE" == "1" ]] && tls_flag=(-k)
  curl "${tls_flag[@]}" $(curl_common_flags) -I "$url" 2>/dev/null || true
}

http_location_header() {
  local url; url="$(trim_ws "${1-}")"
  http_headers "$url" | awk 'tolower($1)=="location:"{print $2; exit}' | tr -d '\r' || true
}

wait_status_in() {
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

nginx_logs_tail() {
  say ""
  say "nginx logs tail (${LOG_TAIL}):"
  dc logs --tail="$LOG_TAIL" nginx 2>/dev/null | sed -n "1,${LOG_TAIL}p" || true
}

assert_nginx_running() {
  local cid
  cid="$(dc ps -q nginx 2>/dev/null || true)"
  [[ -n "$cid" ]] || die "nginx container not found (is the stack running?)"
  [[ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)" == "true" ]] || \
    die "nginx container is not running"
}

assert_http_301_for_path() {
  # Enforce: HTTP 301 for protected locations.
  # /healthz is excluded from the 301 rule (allowed to be 200).
  local path="$1"
  local url="${BASE_HTTP_URL}${path}"
  local code loc

  code="$(http_status "$url")"

  if [[ "$path" == "/healthz" ]]; then
    if [[ "$code" == "200" || "$code" == "301" || "$code" == "302" || "$code" == "308" ]]; then
      loc="$(http_location_header "$url")"
      say "  HTTP  $path : $code ${loc:+-> Location: $loc}"
      return 0
    fi
    say "  HTTP  $path : $code (expected 200 or redirect)"
    http_headers "$url" | sed -n '1,40p' || true
    die "unexpected HTTP status for /healthz"
  fi

  if [[ "$code" != "301" ]]; then
    say "  HTTP  $path : $code (expected 301)"
    http_headers "$url" | sed -n '1,40p' || true
    die "protected path must return HTTP 301: $path"
  fi
  loc="$(http_location_header "$url")"
  say "  HTTP  $path : 301 OK -> Location: ${loc:-<missing>}"
}

assert_https_protected_for_path() {
  # Enforce: HTTPS without creds must be 401/403 for protected locations.
  local path="$1"
  local url="${BASE_HTTPS_URL}${path}"
  local code

  code="$(http_status "$url")"
  if [[ "$code" != "401" && "$code" != "403" ]]; then
    say "  HTTPS $path : $code (expected 401/403)"
    http_headers "$url" | sed -n '1,40p' || true
    nginx_logs_tail
    die "protected path must be auth-gated on HTTPS: $path"
  fi
  say "  HTTPS $path : $code OK (auth required)"
}

get_protected_paths() {
  if [[ -n "${PROTECTED_PATHS_ENV:-}" ]]; then
    # shellcheck disable=SC2206
    local arr=( $PROTECTED_PATHS_ENV )
    printf '%s\n' "${arr[@]}"
  else
    printf '%s\n' "${PROTECTED_PATHS_DEFAULT[@]}"
  fi
}

main() {
  need_cmd docker
  need_cmd curl

  DOMAIN="$(trim_ws "$DOMAIN")"
  BASE_HTTP_URL="$(trim_ws "$BASE_HTTP_URL")"
  BASE_HTTPS_URL="$(trim_ws "$BASE_HTTPS_URL")"

  say "Compose file: $COMPOSE_FILE"
  say "DOMAIN: $DOMAIN"
  say "HTTP:  $BASE_HTTP_URL"
  say "HTTPS: $BASE_HTTPS_URL"
  say ""

  assert_nginx_running

  say "Check: HTTPS /healthz is 200"
  wait_status_in "${BASE_HTTPS_URL}/healthz" "200" || die "HTTPS /healthz did not become 200"
  say "  HTTPS /healthz : 200 OK"
  say ""

  mapfile -t PROTECTED_PATHS < <(get_protected_paths)
  [[ "${#PROTECTED_PATHS[@]}" -gt 0 ]] || die "protected paths list is empty"

  say "Protected locations (explicit list):"
  for p in "${PROTECTED_PATHS[@]}"; do
    say "  - $p"
  done
  say ""

  say "Check: HTTP redirect policy (protected locations must be 301; /healthz excluded)"
  for p in "${PROTECTED_PATHS[@]}"; do
    assert_http_301_for_path "$p"
  done
  say ""

  say "Check: HTTPS access control (protected locations must be 401/403 without creds)"
  for p in "${PROTECTED_PATHS[@]}"; do
    assert_https_protected_for_path "$p"
  done

  say ""
  say "DONE: security checks passed."
}

main "$@"
