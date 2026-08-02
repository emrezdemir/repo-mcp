#!/usr/bin/env bash
#
# Run the gateway and the indexer locally with auto-reload, no Docker.
#
# Authentication is put into development mode (DEV_INSECURE_AUTH) with a static
# token, so there is no Keycloak dependency. Smart tools are off unless you
# point LITELLM_BASE_URL at a proxy.
#
# Usage:
#   scripts/dev.sh              both services
#   scripts/dev.sh gateway      one service
#
# Environment:
#   DEV_STATIC_TOKEN    bearer token to accept (default: devtoken)
#   DEV_STATIC_GROUPS   LDAP groups to impersonate (default: from tenants.yaml)
#   LITELLM_BASE_URL    enables the smart tools when set

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WHICH="${1:-both}"
case "$WHICH" in
  gateway|indexer|both) ;;
  -h|--help) sed -n '2,18p' "$0" | sed 's/^# \?//'; exit 0 ;;
  *) die "unknown argument: $WHICH (try --help)" ;;
esac

[[ -f "$REPO_ROOT/deploy/tenants.yaml" ]] || die "deploy/tenants.yaml is missing — run scripts/setup.sh"
[[ -f "$REPO_ROOT/deploy/scan.yaml" ]] || die "deploy/scan.yaml is missing — run scripts/setup.sh"

# shellcheck disable=SC1091
[[ -f "$REPO_ROOT/deploy/.env" ]] && set -a && source "$REPO_ROOT/deploy/.env" && set +a

DEV_ROOT="${DEV_ROOT:-$REPO_ROOT/.dev}"
mkdir -p "$DEV_ROOT/cache" "$DEV_ROOT/repos"

export DEV_INSECURE_AUTH=true
export DEV_STATIC_TOKEN="${DEV_STATIC_TOKEN:-devtoken}"
export TENANTS_FILE="$REPO_ROOT/deploy/tenants.yaml"
export SCAN_CONFIG="$REPO_ROOT/deploy/scan.yaml"
export CBM_CACHE_ROOT="$DEV_ROOT/cache"
export CBM_REPO_ROOT="$DEV_ROOT/repos"
export CBM_BINARY="${CBM_BINARY:-codebase-memory-mcp}"
export SMART_TOOLS_ENABLED="${SMART_TOOLS_ENABLED:-false}"

# Impersonate the first tenant's first group unless told otherwise, so the
# static token maps to a real squad without extra configuration.
if [[ -z "${DEV_STATIC_GROUPS:-}" ]]; then
  DEV_STATIC_GROUPS="$("$(py_for gateway)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry
import os

registry = TenantRegistry.load(Path(os.environ["TENANTS_FILE"]))
tenant = registry.tenants[0]
groups = set(tenant.ldap_groups)
# Include an admin group if one is configured, so the dev token is not
# accidentally limited to viewer.
for assignment in registry.role_assignments:
    if assignment.role.value == "admin":
        groups |= (assignment.ldap_groups & tenant.ldap_groups)
print(",".join(sorted(groups)))
PY
)"
fi
export DEV_STATIC_GROUPS

if ! command -v "$CBM_BINARY" >/dev/null 2>&1; then
  warn "$CBM_BINARY is not on PATH — gateway tool calls will fail."
  dim "      Install it: https://github.com/DeusData/codebase-memory-mcp"
  dim "      Or:         npm install -g codebase-memory-mcp"
fi

cat <<EOF

${C_BLUE}Development mode${C_RESET} ${C_DIM}(JWT verification disabled)${C_RESET}
  gateway   http://127.0.0.1:8080/mcp
  indexer   http://127.0.0.1:8082
  token     ${DEV_STATIC_TOKEN}
  groups    ${DEV_STATIC_GROUPS}
  data      ${DEV_ROOT}

Try it:
  curl -s http://127.0.0.1:8080/mcp \\
    -H 'Authorization: Bearer ${DEV_STATIC_TOKEN}' \\
    -H 'Content-Type: application/json' \\
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq

EOF

PIDS=()
cleanup() {
  [[ ${#PIDS[@]} -gt 0 ]] && kill "${PIDS[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start() {
  local service="$1" port="$2"
  cd "$REPO_ROOT/$service"
  "$(py_for "$service")" -m uvicorn app.asgi:app \
    --host 127.0.0.1 --port "$port" --reload --reload-dir app &
  PIDS+=($!)
  cd "$REPO_ROOT"
}

[[ "$WHICH" == "gateway" || "$WHICH" == "both" ]] && start gateway 8080
[[ "$WHICH" == "indexer" || "$WHICH" == "both" ]] && start indexer 8082

wait
