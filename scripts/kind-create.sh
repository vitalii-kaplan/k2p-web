#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-k2p}"
K8S_IMAGE="${K8S_IMAGE:-kindest/node:v1.29.2}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v kind >/dev/null 2>&1; then
  echo "ERROR: kind is not installed. Install: brew install kind"
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is not installed. Install: brew install kubectl"
  exit 1
fi

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' already exists."
  kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null
  exit 0
fi

TMP_CFG="$(mktemp)"
cat > "$TMP_CFG" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: ${K8S_IMAGE}
    extraMounts:
      - hostPath: ${REPO_ROOT}
        containerPath: /repo
EOF

echo "Creating kind cluster '$CLUSTER_NAME'..."
kind create cluster --name "$CLUSTER_NAME" --config "$TMP_CFG"
rm -f "$TMP_CFG"

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null
kubectl cluster-info >/dev/null

echo "OK: kind cluster '$CLUSTER_NAME' is ready."
echo "Repo mounted into node at /repo (dev-only)."
