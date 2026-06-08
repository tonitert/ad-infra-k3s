#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-$SCRIPT_DIR/clustername_kubeconfig.yaml}"

LOCAL_PORT="${ARGOCD_LOCAL_PORT:-${1:-8080}}"
NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"

if ! [[ "$LOCAL_PORT" =~ ^[0-9]+$ ]] || (( LOCAL_PORT < 1 || LOCAL_PORT > 65535 )); then
  echo "Invalid local port: $LOCAL_PORT" >&2
  echo "Usage: $0 [local-port]" >&2
  exit 1
fi

PASSWORD="$(
  kubectl -n "$NAMESPACE" get secret argocd-initial-admin-secret \
    -o jsonpath="{.data.password}" | base64 -d
)"

cat <<EOF
Argo CD is available while this script is running:
  URL:      https://localhost:$LOCAL_PORT
  Username: admin
  Password: $PASSWORD

The Argo CD server uses HTTPS. Your browser may warn about its certificate.
Press Ctrl-C to stop the port-forward.

EOF

exec kubectl -n "$NAMESPACE" port-forward --address 127.0.0.1 svc/argocd-server "$LOCAL_PORT:443"
