#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-k2p}"

if ! command -v kind >/dev/null 2>&1; then
  echo "ERROR: kind is not installed."
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <image:tag> [image:tag ...]"
  echo "Example: $0 k2p-web-api:dev k2p-web-runner:dev"
  exit 2
fi

for img in "$@"; do
  echo "Loading image into kind/${CLUSTER_NAME}: ${img}"
  kind load docker-image --name "$CLUSTER_NAME" "$img"
done

echo "OK: images loaded."
