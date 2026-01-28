#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Resetting local database to an empty state..."

# Ensure we operate from repo root
cd "$ROOT_DIR"

# Flush all data and re-apply migrations
python api/manage.py flush --noinput
python api/manage.py migrate

echo "Done."
