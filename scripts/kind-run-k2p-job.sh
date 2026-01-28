#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-k2p}"
NAMESPACE="${NAMESPACE:-k2p}"
JOB_NAME="${JOB_NAME:-k2p-discounts}"
IMAGE="${IMAGE:-ghcr.io/vitalii-kaplan/knime2py:main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INPUT_HOST="${REPO_ROOT}/tests/data/discounts.zip"
OUTPUT_HOST="${REPO_ROOT}/tests/out-k8s"

if [[ ! -f "$INPUT_HOST" ]]; then
  echo "ERROR: input zip not found: $INPUT_HOST"
  exit 1
fi

mkdir -p "$OUTPUT_HOST"
chmod 777 "$OUTPUT_HOST" || true

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE" >/dev/null

# Clean up previous run if present
kubectl -n "$NAMESPACE" delete job "$JOB_NAME" --ignore-not-found >/dev/null

cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: k2p
          image: ${IMAGE}
          args: ["--in-zip", "/in/discounts.zip", "--out", "/out"]
          env:
            - name: PYTHONDONTWRITEBYTECODE
              value: "1"
          volumeMounts:
            - name: inzip
              mountPath: /in/discounts.zip
              readOnly: true
            - name: outdir
              mountPath: /out
      volumes:
        - name: inzip
          hostPath:
            path: /repo/tests/data/discounts.zip
            type: File
        - name: outdir
          hostPath:
            path: /repo/tests/out-k8s
            type: DirectoryOrCreate
EOF

echo "Waiting for job to complete..."
kubectl -n "$NAMESPACE" wait --for=condition=complete "job/${JOB_NAME}" --timeout=300s || true

echo
echo "Job logs:"
kubectl -n "$NAMESPACE" logs "job/${JOB_NAME}" || true

echo
echo "Outputs written to: ${OUTPUT_HOST}"
ls -la "$OUTPUT_HOST" || true
