#!/usr/bin/env bash
set -euo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: Homebrew is required."
  exit 1
fi

brew bundle --no-upgrade
echo "OK: tools installed."
