#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${1:-k2p}"
OUT="${2:-var/kubeconfig-kind.yaml}"

mkdir -p "$(dirname "$OUT")"

# Export kubeconfig (contains certs/keys inline)
kind get kubeconfig --name "$CLUSTER" > "$OUT"

# Inside Docker network, the API server is reachable via the node container name.
# For kind cluster "k2p", that's "k2p-control-plane:6443".
python - "$OUT" "$CLUSTER" <<'PY'
import re, sys
path = sys.argv[1]
cluster = sys.argv[2]
control_plane = f"{cluster}-control-plane"
data = open(path, "r", encoding="utf-8").read()

# Replace any https://127.0.0.1:<port> or https://localhost:<port> with https://<control-plane>:6443
data2 = re.sub(r"server:\s*https://(127\.0\.0\.1|localhost):\d+",
               f"server: https://{control_plane}:6443", data)

open(path, "w", encoding="utf-8").write(data2)
print(f"Wrote {path} with server=https://{control_plane}:6443")
PY
