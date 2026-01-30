#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${1:-k2p}"
OUT_PATH="${2:-var/kubeconfig-kind.yaml}"

mkdir -p "$(dirname "$OUT_PATH")"

# Rewrite the server so it works from inside containers on the "kind" network
kind get kubeconfig --name "$CLUSTER_NAME" \
  | sed -E 's#server: https://127\.0\.0\.1:[0-9]+#server: https://k2p-control-plane:6443#g' \
  > "$OUT_PATH"

echo "Wrote $OUT_PATH (server rewritten to https://k2p-control-plane:6443)"
