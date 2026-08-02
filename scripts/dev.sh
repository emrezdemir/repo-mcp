#!/usr/bin/env bash
#
# Run the gateway and the indexer locally with auto-reload, no Docker.
#
# Authentication is put into development mode (DEV_INSECURE_AUTH) with a static
# token, so there is no Keycloak dependency. Smart tools are off unless you
# point LITELLM_BASE_URL at a proxy.
#
# Configuration lives in a database, so this creates a local SQLite one under
# .dev/ and seeds it from deploy/tenants.yaml and deploy/scan.yaml. SQLite is
# for one machine only; anything shared uses PostgreSQL (docs/environments.md).
#
# Usage:
#   scripts/dev.sh              both services
#   scripts/dev.sh gateway      one service
#
# Environment:
#   DEV_STATIC_TOKEN    bearer token to accept (default: devtoken)
#   DEV_STATIC_GROUPS   LDAP groups to impersonate (default: from tenants.yaml)
#   DATABASE_URL        use another database instead of the local SQLite one
#   DEV_RESEED          set to 1 to re-import the YAML documents on every start
#   LITELLM_BASE_URL    enables the smart tools when set

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WHICH="${1:-both}"
case "$WHICH" in
  gateway|indexer|both) ;;
  -h|--help) sed -n '2,22p' "$0" | sed 's/^# \?//'; exit 0 ;;
  *) die "unknown argument: $WHICH (try --help)" ;;
esac

[[ -f "$REPO_ROOT/deploy/tenants.yaml" ]] || die "deploy/tenants.yaml is missing — run scripts/setup.sh"
[[ -f "$REPO_ROOT/deploy/scan.yaml" ]] || die "deploy/scan.yaml is missing — run scripts/setup.sh"

# shellcheck disable=SC1091
[[ -f "$REPO_ROOT/deploy/.env" ]] && set -a && source "$REPO_ROOT/deploy/.env" && set +a

DEV_ROOT="${DEV_ROOT:-$REPO_ROOT/.dev}"
mkdir -p "$DEV_ROOT/cache" "$DEV_ROOT/repos"

# Overridable, so a real identity provider can be pointed at locally:
#   DEV_INSECURE_AUTH=false scripts/dev.sh gateway
# with oidc.issuer and oidc.browser_client_id set in the database.
export DEV_INSECURE_AUTH="${DEV_INSECURE_AUTH:-true}"
export DEV_STATIC_TOKEN="${DEV_STATIC_TOKEN:-devtoken}"
export SCAN_CONFIG="$REPO_ROOT/deploy/scan.yaml"
export CBM_CACHE_ROOT="$DEV_ROOT/cache"
export CBM_REPO_ROOT="$DEV_ROOT/repos"
export CBM_BINARY="${CBM_BINARY:-codebase-memory-mcp}"
export SMART_TOOLS_ENABLED="${SMART_TOOLS_ENABLED:-false}"
export ENVIRONMENT="${ENVIRONMENT:-local}"

# ── database ──────────────────────────────────────────────────────────
# Everything an administrator can change lives here, not in a file. SQLite
# keeps the no-Docker promise; the schema and the code are the same ones
# PostgreSQL gets.

export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$DEV_ROOT/repo-mcp.db}"
export MIGRATE_ON_START=true

if [[ -z "${SECRETS_KEY:-}" ]]; then
  # Stable across restarts, or every stored credential becomes unreadable.
  KEY_FILE="$DEV_ROOT/secrets.key"
  [[ -f "$KEY_FILE" ]] || {
    "$(py_for common)" -m repo_mcp_common.cli generate-key > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
  }
  SECRETS_KEY="$(cat "$KEY_FILE")"
fi
export SECRETS_KEY

ADMIN="$(py_for common)"
FRESH=0
[[ -f "$DEV_ROOT/repo-mcp.db" ]] || FRESH=1

log "preparing the development database"
"$ADMIN" -m repo_mcp_common.cli init-db >/dev/null || die "could not create the schema"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}" ADMIN_PASSWORD="${ADMIN_PASSWORD:-devadmin-password}" \
  "$ADMIN" -m repo_mcp_common.cli create-admin >/dev/null 2>&1 || true

if (( FRESH )) || [[ "${DEV_RESEED:-0}" == "1" ]]; then
  "$ADMIN" -m repo_mcp_common.cli import \
    --tenants "$REPO_ROOT/deploy/tenants.yaml" \
    --scan "$REPO_ROOT/deploy/scan.yaml" >/dev/null \
    || die "could not import deploy/tenants.yaml and deploy/scan.yaml"
  ok "seeded from deploy/tenants.yaml and deploy/scan.yaml"
else
  dim "      database already seeded (DEV_RESEED=1 to re-import)"
fi

# Impersonate the first tenant's first group unless told otherwise, so the
# static token maps to a real squad without extra configuration.
if [[ -z "${DEV_STATIC_GROUPS:-}" ]]; then
  DEV_STATIC_GROUPS="$("$(py_for gateway)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry

registry = TenantRegistry.load(Path("deploy/tenants.yaml"))
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
  dim "      Install the indexing engine (see NOTICE), or set CBM_BINARY."
  dim "      Everything except tool execution works without it."
fi

cat <<EOF

${C_BLUE}Development mode${C_RESET} ${C_DIM}(JWT verification disabled)${C_RESET}
  gateway   http://127.0.0.1:8080/mcp
  indexer   http://127.0.0.1:8082
  token     ${DEV_STATIC_TOKEN}
  groups    ${DEV_STATIC_GROUPS}
  data      ${DEV_ROOT}
  database  ${DATABASE_URL}
  admin     ${ADMIN_USERNAME:-admin} / ${ADMIN_PASSWORD:-devadmin-password}  ${C_DIM}(POST /admin/login)${C_RESET}

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
  # A subshell rather than cd-and-cd-back: uvicorn needs the service directory
  # on its path, and a failed return would leave the next service starting from
  # the wrong tree.
  (
    cd "$REPO_ROOT/$service" || die "cannot enter $service"
    exec "$(py_for "$service")" -m uvicorn app.asgi:app \
      --host 127.0.0.1 --port "$port" --reload --reload-dir app
  ) &
  PIDS+=($!)
}

[[ "$WHICH" == "gateway" || "$WHICH" == "both" ]] && start gateway 8080
[[ "$WHICH" == "indexer" || "$WHICH" == "both" ]] && start indexer 8082

wait
