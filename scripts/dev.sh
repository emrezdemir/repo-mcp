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
#   scripts/dev.sh              both services, in the foreground (Ctrl-C stops)
#   scripts/dev.sh gateway      one service
#   scripts/dev.sh --start      start in the background and return
#   scripts/dev.sh --stop       stop what --start started
#   scripts/dev.sh --status     say whether it is running, and answer /healthz
#   scripts/dev.sh --logs       follow the background log
#
# The foreground form is what you want while writing code — auto-reload, logs on
# screen. --start is for the other loop: bring it up, poke it, tear it down,
# without giving up a terminal. The Docker stack has had up/down/logs since the
# beginning and the local path had nothing, so this was a pkill by hand.
#
# Environment:
#   DEV_STATIC_TOKEN    bearer token to accept (default: devtoken)
#   DEV_STATIC_GROUPS   LDAP groups to impersonate (default: from tenants.yaml)
#   DATABASE_URL        use another database instead of the local SQLite one
#   DEV_RESEED          set to 1 to re-import the YAML documents on every start
#   LITELLM_BASE_URL    enables the smart tools when set

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ACTION=run
WHICH=both
for arg in "$@"; do
  case "$arg" in
    gateway|indexer|both) WHICH="$arg" ;;
    --start)   ACTION=start ;;
    --stop)    ACTION=stop ;;
    --status)  ACTION=status ;;
    --logs)    ACTION=logs ;;
    -h|--help) sed -n '2,31p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

# Resolved before anything else needs it: --stop, --status and --logs act on a
# run that already exists and must not require configuration, a database or a
# virtualenv to do it.
DEV_ROOT="${DEV_ROOT:-$REPO_ROOT/.dev}"
PID_FILE="$DEV_ROOT/dev.pid"
LOG_FILE="$DEV_ROOT/dev.log"

#: The recorded process, if it is still alive and still ours. A PID file
#: outlives its process and PIDs get reused, so the command line is checked
#: before anything is signalled — killing a stranger that inherited the number
#: would be a genuinely nasty thing for a convenience script to do.
running_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(head -1 "$PID_FILE" 2>/dev/null | tr -dc '0-9')"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -o command= -p "$pid" 2>/dev/null | grep -q 'dev\.sh' || return 1
  printf '%s' "$pid"
}

health() {
  curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$1/healthz" 2>/dev/null
}

case "$ACTION" in
  status)
    if pid="$(running_pid)"; then
      ok "running in the background (pid $pid)"
    else
      [[ -f "$PID_FILE" ]] && dim "      a stale $PID_FILE is left over; --stop clears it"
      dim "      not running in the background"
    fi
    health 8080 && ok "gateway answers on 8080" || dim "      gateway does not answer on 8080"
    health 8082 && ok "indexer answers on 8082" || dim "      indexer does not answer on 8082"
    exit 0
    ;;
  logs)
    [[ -f "$LOG_FILE" ]] || die "no log at $LOG_FILE — nothing was started with --start"
    exec tail -f "$LOG_FILE"
    ;;
  stop)
    if ! pid="$(running_pid)"; then
      rm -f "$PID_FILE"
      ok "nothing to stop"
      exit 0
    fi
    log "stopping (pid $pid)"
    # TERM the supervisor; its EXIT trap kills the uvicorn children it started,
    # which is why they are not signalled individually here.
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 25); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      warn "it did not stop on TERM; sending KILL"
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    # The ports are the honest test: the supervisor is gone, but a child that
    # ignored its parent's trap would still be holding one.
    if health 8080 || health 8082; then
      warn "something is still answering on 8080 or 8082 — not started by --start"
    fi
    ok "stopped"
    exit 0
    ;;
esac

if [[ "$ACTION" == "start" ]] && pid="$(running_pid)"; then
  die "already running in the background (pid $pid) — 'scripts/dev.sh --stop' first"
fi

[[ -f "$REPO_ROOT/deploy/tenants.yaml" ]] || die "deploy/tenants.yaml is missing — run scripts/setup.sh"
[[ -f "$REPO_ROOT/deploy/scan.yaml" ]] || die "deploy/scan.yaml is missing — run scripts/setup.sh"

# --start is this same script again, detached, with its output in a file. Doing
# it that way rather than backgrounding the two services separately means the
# supervisor's existing EXIT trap still owns their lifetime, so --stop has one
# process to signal and no child can be orphaned.
if [[ "$ACTION" == "start" ]]; then
  mkdir -p "$DEV_ROOT"
  # An absolute path, not "$0": lib.sh moves us to the repository root, so a
  # relative "./dev.sh" from the caller's directory no longer resolves here.
  nohup "$REPO_ROOT/scripts/dev.sh" "$WHICH" >"$LOG_FILE" 2>&1 &
  supervisor=$!
  echo "$supervisor" > "$PID_FILE"
  log "starting in the background (pid $supervisor)"
  for _ in $(seq 1 60); do
    health 8080 && break
    kill -0 "$supervisor" 2>/dev/null || { fail "it exited during startup:"; tail -15 "$LOG_FILE"; rm -f "$PID_FILE"; exit 1; }
    sleep 1
  done
  if health 8080; then
    ok "gateway is up on 8080"
    health 8082 && ok "indexer is up on 8082" || warn "indexer is not answering yet"
  else
    warn "the gateway did not answer within 60s — 'scripts/dev.sh --logs' to see why"
  fi
  # The banner with the token went to the log, because the services own the
  # terminal the caller did not want to give up. Repeat it here: the interface
  # asks for that token on its sign-in screen and tells you `make dev` prints
  # it, which is no help at all to someone who started it this way.
  if [[ -f "$LOG_FILE" ]]; then
    sed -n '/Development mode/,/^$/p' "$LOG_FILE"
  fi
  dim "      interface:  http://127.0.0.1:8080/ui"
  dim "      logs:  scripts/dev.sh --logs        stop:  scripts/dev.sh --stop"
  exit 0
fi

# Captured before deploy/.env is sourced, and only what the *shell* set counts.
# That file describes the Docker stack, where identity is normally Keycloak, so
# `make setup` writes DEV_INSECURE_AUTH=false into it by default. Sourcing it
# with `set -a` turns that into an environment variable, and the ${VAR:-true}
# below then never applies — so `make dev` announced "JWT verification
# disabled", printed a token, and answered 401 to that very token. The .env
# value is about the containers; this script is the no-Docker path and picks
# its own default, while an explicit
#   DEV_INSECURE_AUTH=false scripts/dev.sh gateway
# still wins, which is the override the header documents.
DEV_AUTH_FROM_SHELL="${DEV_INSECURE_AUTH:-}"

# shellcheck disable=SC1091
[[ -f "$REPO_ROOT/deploy/.env" ]] && set -a && source "$REPO_ROOT/deploy/.env" && set +a

DEV_ROOT="${DEV_ROOT:-$REPO_ROOT/.dev}"
mkdir -p "$DEV_ROOT/cache" "$DEV_ROOT/repos"

# Overridable, so a real identity provider can be pointed at locally:
#   DEV_INSECURE_AUTH=false scripts/dev.sh gateway
# with oidc.issuer and oidc.browser_client_id set in the database.
export DEV_INSECURE_AUTH="${DEV_AUTH_FROM_SHELL:-true}"
export DEV_STATIC_TOKEN="${DEV_STATIC_TOKEN:-devtoken}"
export SCAN_CONFIG="$REPO_ROOT/deploy/scan.yaml"
export CBM_CACHE_ROOT="$DEV_ROOT/cache"
export CBM_REPO_ROOT="$DEV_ROOT/repos"
export CBM_BINARY="${CBM_BINARY:-codebase-memory-mcp}"
export SMART_TOOLS_ENABLED="${SMART_TOOLS_ENABLED:-false}"

# Vite writes to gateway/webui/dist; the gateway looks in gateway/app/ui unless
# told otherwise, and nothing connected the two — so /ui answered 500 on every
# local run while working perfectly in the image, which sets this itself. An
# explicit REPO_MCP_UI_DIR still wins.
if [[ -z "${REPO_MCP_UI_DIR:-}" && -f "$REPO_ROOT/gateway/webui/dist/index.html" ]]; then
  export REPO_MCP_UI_DIR="$REPO_ROOT/gateway/webui/dist"
fi
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

# The banner says what is actually true. It used to announce "JWT verification
# disabled" and print a token unconditionally, which was a lie whenever
# something had switched verification back on — and the token it offered
# answered 401.
if [[ "$DEV_INSECURE_AUTH" == "true" ]]; then
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
else
  cat <<EOF

${C_BLUE}Development mode${C_RESET} ${C_YELLOW}(JWT verification is ON)${C_RESET}
  gateway   http://127.0.0.1:8080/mcp
  indexer   http://127.0.0.1:8082
  data      ${DEV_ROOT}
  database  ${DATABASE_URL}
  admin     ${ADMIN_USERNAME:-admin} / ${ADMIN_PASSWORD:-devadmin-password}  ${C_DIM}(POST /admin/login)${C_RESET}

${C_DIM}No static token: every MCP call needs a real OIDC token, and the gateway
refuses with "OIDC_ISSUER is not configured" until oidc.issuer is set. Drop
DEV_INSECURE_AUTH=false to get the static-token mode back.${C_RESET}

EOF
fi

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
