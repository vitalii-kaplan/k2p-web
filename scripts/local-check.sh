#!/usr/bin/env bash
set -euo pipefail

# local-check.sh
# Purpose: deterministic local stack reset + bring-up with verification.
#
# Usage:
#   ./scripts/local-check.sh
#
# Optional env flags:
#   WIPE_VOLUMES=1      # also removes volumes (DESTRUCTIVE: deletes Postgres data)
#   START_WORKER=1      # attempt to start worker if module exists
#   SKIP_HTTP=1         # skip curl checks
#   API_URL=http://127.0.0.1:8000

API_URL="${API_URL:-http://127.0.0.1:8000}"
WIPE_VOLUMES="${WIPE_VOLUMES:-0}"
START_WORKER="${START_WORKER:-0}"
SKIP_HTTP="${SKIP_HTTP:-0}"

say()  { printf '%s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

# ---------- preflight ----------
need_cmd docker
need_cmd sed
need_cmd grep
need_cmd awk

# Docker daemon reachable?
docker info >/dev/null 2>&1 || die "docker daemon is not reachable (is Docker Desktop running? correct docker context?)"

# Repo root (best-effort)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

[[ -f docker-compose.yml ]] || die "docker-compose.yml not found in $REPO_ROOT"
[[ -f .env ]] || die ".env not found in $REPO_ROOT"

# Compose v2 plugin present?
docker compose version >/dev/null 2>&1 || die "docker compose plugin not available (try 'docker compose version')"

say "Repo: $REPO_ROOT"
say "Docker context: $(docker context show 2>/dev/null || true)"
say "Compose file: docker-compose.yml"
say "API_URL: $API_URL"
say "WIPE_VOLUMES=$WIPE_VOLUMES START_WORKER=$START_WORKER SKIP_HTTP=$SKIP_HTTP"
say ""

# ---------- read .env (minimal sanity) ----------
env_get() {
  # prints value or empty
  local key="$1"
  awk -F= -v k="$key" 'BEGIN{v=""} $1==k{v=$0; sub(/^[^=]*=/,"",v); print v; exit}' .env 2>/dev/null || true
}

DJANGO_DEBUG="$(env_get DJANGO_DEBUG)"
DJANGO_SECRET_KEY="$(env_get DJANGO_SECRET_KEY)"
DB_ENGINE_ENV="$(env_get DB_ENGINE)"

[[ -n "$DJANGO_SECRET_KEY" ]] || die "DJANGO_SECRET_KEY is empty/missing in .env"
[[ "$DJANGO_DEBUG" == "0" || "$DJANGO_DEBUG" == "1" ]] || die "DJANGO_DEBUG must be 0 or 1 in .env (got: '$DJANGO_DEBUG')"
[[ -n "$DB_ENGINE_ENV" ]] || die "DB_ENGINE is empty/missing in .env (expected 'postgres' for this setup)"

say ".env checks:"
say "  DJANGO_DEBUG=$DJANGO_DEBUG"
say "  DB_ENGINE=$DB_ENGINE_ENV"
say "  DJANGO_SECRET_KEY=set"
say ""

# Your settings.py expects DB_ENGINE == "postgres" (not a Django backend string).
if [[ "$DB_ENGINE_ENV" != "postgres" && "$DB_ENGINE_ENV" != "sqlite" ]]; then
  say "WARNING: .env DB_ENGINE is '$DB_ENGINE_ENV'."
  say "         Your settings.py likely expects 'postgres' or 'sqlite'."
  say ""
fi

# ---------- teardown ----------
say "Step 1: Teardown"
if [[ "$WIPE_VOLUMES" == "1" ]]; then
  say "  Running: docker compose down -v (DESTRUCTIVE)"
  docker compose down -v
else
  say "  Running: docker compose down"
  docker compose down
fi
say ""

# ---------- start postgres ----------
say "Step 2: Start Postgres"
docker compose up -d postgres

POSTGRES_CID="$(docker compose ps -q postgres || true)"
[[ -n "$POSTGRES_CID" ]] || die "postgres container id not found after start"

say "  postgres container: $POSTGRES_CID"
say "  waiting for health=healthy ..."

# Wait up to ~60s (30 * 2s)
for i in $(seq 1 30); do
  HS="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$POSTGRES_CID" 2>/dev/null || echo "unknown")"
  if [[ "$HS" == "healthy" ]]; then
    say "  postgres is healthy"
    break
  fi
  if [[ "$i" == "30" ]]; then
    docker logs --tail=200 "$POSTGRES_CID" || true
    die "postgres did not become healthy (last health status: $HS)"
  fi
  sleep 2
done
say ""

# ---------- config sanity: ensure compose isn't overriding DB_ENGINE to a wrong value ----------
say "Step 3: Verify compose environment for api"
# Print resolved env vars for api (using ephemeral run container)
API_ENV="$(docker compose run --rm api env | egrep '^(DB_ENGINE|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|DJANGO_DEBUG|DJANGO_SECRET_KEY)=' || true)"
say "$API_ENV"
say ""

API_DB_ENGINE="$(printf '%s\n' "$API_ENV" | awk -F= '$1=="DB_ENGINE"{print $2}')"
if [[ -z "$API_DB_ENGINE" ]]; then
  die "api container did not get DB_ENGINE at all. Fix docker-compose.yml / .env injection."
fi
if [[ "$API_DB_ENGINE" != "postgres" && "$API_DB_ENGINE" != "sqlite" ]]; then
  say "ERROR: api DB_ENGINE is '$API_DB_ENGINE'."
  say "Your settings.py expects DB_ENGINE=='postgres' to use Postgres."
  say "Fix docker-compose.yml: do NOT set DB_ENGINE to 'django.db.backends.postgresql'. Use 'postgres' (or omit DB_ENGINE and rely on .env)."
  exit 1
fi

# ---------- migrations ----------
say "Step 4: Run migrations (prefer without --skip-checks)"
set +e
docker compose run --rm api python manage.py migrate
MIG_RC=$?
set -e
if [[ "$MIG_RC" != "0" ]]; then
  say ""
  say "Migrate failed without --skip-checks. Retrying with --skip-checks."
  docker compose run --rm api python manage.py migrate --skip-checks || die "migrate failed even with --skip-checks"
fi
say ""

# ---------- validate tables in Postgres ----------
say "Step 5: Validate Postgres tables"
# This requires psql inside postgres image (it is there).
docker compose exec -T postgres psql -U "${DB_USER:-k2pweb}" -d "${DB_NAME:-k2pweb}" -c '\dt' || die "psql table listing failed"
say ""

# ---------- start api ----------
say "Step 6: Start API"
docker compose up -d api

API_CID="$(docker compose ps -q api || true)"
[[ -n "$API_CID" ]] || die "api container id not found after start"

# Wait for container to be running
say "  api container: $API_CID"
say "  waiting for api to be running ..."
for i in $(seq 1 30); do
  RUNNING="$(docker inspect -f '{{.State.Running}}' "$API_CID" 2>/dev/null || echo "false")"
  if [[ "$RUNNING" == "true" ]]; then
    say "  api is running"
    break
  fi
  # If it exited, show logs and fail
  STATUS="$(docker inspect -f '{{.State.Status}} exit={{.State.ExitCode}}' "$API_CID" 2>/dev/null || true)"
  if [[ "$STATUS" == exited* ]]; then
    docker logs --tail=200 "$API_CID" || true
    die "api exited early ($STATUS)"
  fi
  sleep 1
done
say ""

# ---------- confirm Django is actually using Postgres ----------
say "Step 7: Confirm Django DATABASES engine"

DB_INFO="$(docker compose exec -T api python manage.py shell -c \
'from django.conf import settings; d=settings.DATABASES["default"]; print(d.get("ENGINE"), d.get("NAME"), d.get("HOST",""), d.get("PORT",""))' \
2>&1)"
RC=$?

if [[ "$RC" != "0" ]]; then
  say "$DB_INFO"
  docker compose logs --tail=200 api || true
  die "failed to read DATABASES from running api container"
fi

say "  DATABASES[default]: $DB_INFO"
if ! echo "$DB_INFO" | grep -q "django.db.backends.postgresql"; then
  die "Django is not using Postgres (expected django.db.backends.postgresql)."
fi
say ""


# ---------- HTTP checks ----------
if [[ "$SKIP_HTTP" != "1" ]]; then
  need_cmd curl
  say "Step 8: HTTP checks"
  # Retry quickly up to ~30s
  ok=0
  for i in $(seq 1 30); do
    if curl -fsS "$API_URL/" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
  done
  if [[ "$ok" != "1" ]]; then
    docker logs --tail=200 "$API_CID" || true
    die "API did not respond on $API_URL/ (check runserver binding/ports, Django errors, or firewall)"
  fi

  say "  GET $API_URL/ : OK"
  # api/ may 404 depending on urls; this is just a reachability check.
  curl -i "$API_URL/api/" | sed -n '1,20p' || true
  say ""
fi

# ---------- worker (optional) ----------
if [[ "$START_WORKER" == "1" ]]; then
  say "Step 9: Worker start (optional)"
  SPEC="$(docker compose run --rm api python -c "import importlib.util as u; print('yes' if u.find_spec('k2pweb.worker') else 'no')")"
  if [[ "$SPEC" != "yes" ]]; then
    say "Worker module k2pweb.worker not found. Skipping worker start."
    say "Fix your worker entrypoint (module/package path) before enabling START_WORKER=1."
  else
    docker compose up -d worker
    WORKER_CID="$(docker compose ps -q worker || true)"
    say "  worker container: $WORKER_CID"
    docker logs --tail=50 "$WORKER_CID" || true
  fi
  say ""
fi

say "DONE: local stack is up and verified."
say "Summary:"
docker compose ps
