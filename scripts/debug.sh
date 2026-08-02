#!/usr/bin/env bash
#
# Diagnose a repo-mcp setup. Runs every check and reports all findings rather
# than stopping at the first failure, because the useful answer is usually the
# combination.
#
# Usage:
#   scripts/debug.sh                     check the local/dev setup
#   scripts/debug.sh --docker            check the Docker stack instead
#   scripts/debug.sh --gateway URL       point at a specific gateway
#   scripts/debug.sh --token TOKEN       bearer token to authenticate with
#   scripts/debug.sh --tenant NAME       squad to use for tool calls

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
INDEXER_URL="${INDEXER_URL:-http://127.0.0.1:8082}"
TOKEN="${DEV_STATIC_TOKEN:-devtoken}"
TENANT="${TENANT:-}"
MODE=local

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker)  MODE=docker ;;
    --gateway) GATEWAY_URL="$2"; shift ;;
    --indexer) INDEXER_URL="$2"; shift ;;
    --token)   TOKEN="$2"; shift ;;
    --tenant)  TENANT="$2"; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

# shellcheck disable=SC1091
[[ -f "$REPO_ROOT/deploy/.env" ]] && set -a && source "$REPO_ROOT/deploy/.env" && set +a

ISSUES=()
note_issue() { ISSUES+=("$1"); fail "$1"; }

# ── 1. toolchain ──────────────────────────────────────────────────────

log "toolchain"
for tool in python3 git curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool $(command -v "$tool")"
  else
    note_issue "$tool is not installed"
  fi
done
command -v jq >/dev/null 2>&1 || warn "jq is not installed; output will be unformatted"

if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  ok "python $(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
else
  note_issue "python 3.11+ is required"
fi

# ── 2. engine ─────────────────────────────────────────────────────────

log "indexing engine"
CBM="${CBM_BINARY:-codebase-memory-mcp}"
if command -v "$CBM" >/dev/null 2>&1; then
  ok "binary $(command -v "$CBM")"
  if version="$("$CBM" --version 2>&1 | head -1)"; then
    ok "version $version"
    dim "      all processes sharing a cache root must run this exact build"
  else
    note_issue "engine --version failed ($CBM)"
  fi
else
  if [[ "$MODE" == "docker" ]]; then
    dim "      not on the host PATH — expected, it lives inside the containers"
  else
    note_issue "engine binary not on PATH: $CBM (needed by scripts/dev.sh)"
  fi
fi

# ── 3. configuration ──────────────────────────────────────────────────

log "configuration"
for name in tenants scan; do
  if [[ -f "$REPO_ROOT/deploy/$name.yaml" ]]; then
    ok "deploy/$name.yaml exists"
  else
    note_issue "deploy/$name.yaml is missing — run scripts/setup.sh"
  fi
done

if [[ -f "$REPO_ROOT/deploy/tenants.yaml" ]]; then
  if output="$("$(py_for gateway)" - 2>&1 <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry

registry = TenantRegistry.load(Path("deploy/tenants.yaml"))
for tenant in registry.tenants:
    flag = " ".join(tenant.cbm_profile_flag()) or "(full profile)"
    print(f"tenant {tenant.name}: profile={tenant.tool_profile} {flag}")
    print(f"    groups:   {', '.join(sorted(tenant.ldap_groups))}")
    print(f"    projects: {', '.join(tenant.projects)}")
    if tenant.structural_only:
        print("    structural_only: source-reading tools withheld")
for assignment in registry.role_assignments:
    print(f"role {assignment.role.value}: {', '.join(sorted(assignment.ldap_groups))}")
PY
  )"; then
    ok "tenants.yaml is valid"
    echo "$output" | sed 's/^/      /'
  else
    note_issue "tenants.yaml is invalid"
    echo "$output" | tail -5 | sed 's/^/      /'
  fi
fi

if [[ -f "$REPO_ROOT/deploy/scan.yaml" ]]; then
  if output="$("$(py_for indexer)" - 2>&1 <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, "indexer")
from app.repos import ScanConfig

config = ScanConfig.load(Path("deploy/scan.yaml"), Path("/var/lib/repo-mcp/repos"))
for connector in config.connectors:
    have = "set" if os.getenv(connector.secret_env) else "MISSING"
    print(f"connector {connector.name}: {connector.kind} -> tenant={connector.tenant} "
          f"mode={connector.mode} {connector.secret_env}={have}")
PY
  )"; then
    ok "scan.yaml is valid"
    echo "$output" | sed 's/^/      /'
    if grep -q MISSING <<<"$output"; then
      note_issue "one or more provider tokens are unset — discovery will fail"
    fi
  else
    note_issue "scan.yaml is invalid"
    echo "$output" | tail -5 | sed 's/^/      /'
  fi
fi

# ── 4. storage ────────────────────────────────────────────────────────

log "storage"
CACHE_ROOT="${CBM_CACHE_ROOT:-$REPO_ROOT/.dev/cache}"
if [[ -d "$CACHE_ROOT" ]]; then
  ok "cache root $CACHE_ROOT"
  count=$(find "$CACHE_ROOT" -name '*.db' 2>/dev/null | wc -l | tr -d ' ')
  dim "      $count indexed project(s)"
  find "$CACHE_ROOT" -name '*.db' 2>/dev/null | head -10 | while read -r db; do
    size=$(du -h "$db" 2>/dev/null | cut -f1)
    dim "      $size  ${db#"$CACHE_ROOT"/}"
  done
  # A store outside its tenant's allowlist leaks its name through
  # list_projects, which means the indexer wrote it to the wrong place.
  "$(py_for gateway)" - 2>/dev/null <<PY | sed 's/^/      /'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry

try:
    registry = TenantRegistry.load(Path("deploy/tenants.yaml"))
except Exception:
    sys.exit(0)
root = Path("$CACHE_ROOT") / "tenant"
for tenant in registry.tenants:
    directory = root / tenant.name
    if not directory.is_dir() or "*" in tenant.projects:
        continue
    stray = sorted(db.stem for db in directory.glob("*.db")
                   if not tenant.allows_project(db.stem))
    if stray:
        print(f"WARNING {tenant.name}: outside allowlist: {', '.join(stray)}")
PY
else
  dim "      cache root $CACHE_ROOT does not exist yet (nothing indexed)"
fi

if command -v df >/dev/null 2>&1 && [[ -d "$CACHE_ROOT" ]]; then
  dim "      $(df -h "$CACHE_ROOT" | tail -1 | awk '{print $4" free of "$2}')"
fi

# ── 5. containers ─────────────────────────────────────────────────────

if [[ "$MODE" == "docker" ]]; then
  log "containers"
  if compose ps --format '{{.Service}} {{.State}} {{.Status}}' 2>/dev/null | sed 's/^/      /'; then
    unhealthy="$(compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep -v ' running' || true)"
    [[ -n "$unhealthy" ]] && note_issue "some services are not running"
  else
    note_issue "docker compose ps failed — is the stack up?"
  fi
fi

# ── 6. services ───────────────────────────────────────────────────────

log "services"
if curl -fsS --max-time 5 "$GATEWAY_URL/healthz" >/dev/null 2>&1; then
  ok "gateway reachable at $GATEWAY_URL"
  ready="$(curl -fsS --max-time 5 "$GATEWAY_URL/readyz" 2>/dev/null || echo '{}')"
  echo "      $ready"
else
  note_issue "gateway is not reachable at $GATEWAY_URL"
fi

if curl -fsS --max-time 5 "$INDEXER_URL/healthz" >/dev/null 2>&1; then
  ok "indexer reachable at $INDEXER_URL"
  echo "      $(curl -fsS --max-time 5 "$INDEXER_URL/healthz" 2>/dev/null)"
  repos="$(curl -fsS --max-time 10 "$INDEXER_URL/repos" 2>/dev/null || echo '{}')"
  if command -v jq >/dev/null 2>&1; then
    dim "      discovered repositories: $(jq -r '.count // 0' <<<"$repos")"
  fi
else
  note_issue "indexer is not reachable at $INDEXER_URL"
fi

# ── 7. MCP round trip ─────────────────────────────────────────────────

log "MCP round trip"
headers=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json')
[[ -n "$TENANT" ]] && headers+=(-H "X-Tenant: $TENANT")

response="$(curl -sS --max-time 20 -w '\n%{http_code}' "$GATEWAY_URL/mcp" \
  "${headers[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' 2>/dev/null || true)"
status="$(tail -1 <<<"$response")"
body="$(sed '$d' <<<"$response")"

case "$status" in
  200)
    if command -v jq >/dev/null 2>&1; then
      names="$(jq -r '.result.tools[]?.name' <<<"$body" 2>/dev/null | tr '\n' ' ')"
      if [[ -n "$names" ]]; then
        ok "tools/list returned: $names"
      else
        note_issue "tools/list returned no tools"
        echo "      $body" | head -3
      fi
    else
      ok "tools/list returned HTTP 200"
    fi
    ;;
  401) note_issue "authentication failed (HTTP 401) — wrong token, or DEV_INSECURE_AUTH is off"
       dim "      $body" ;;
  403) note_issue "authorization failed (HTTP 403)"
       dim "      $body"
       dim "      if you belong to several squads, pass --tenant NAME" ;;
  000) note_issue "no response from the gateway" ;;
  *)   note_issue "unexpected HTTP $status from the gateway"
       dim "      $body" ;;
esac

# ── 8. model backend ──────────────────────────────────────────────────

log "model backend"
if [[ -n "${LITELLM_BASE_URL:-}" ]]; then
  if curl -fsS --max-time 5 "${LITELLM_BASE_URL%/}/health/liveliness" >/dev/null 2>&1 \
     || curl -fsS --max-time 5 "${LITELLM_BASE_URL%/}/health" >/dev/null 2>&1; then
    ok "LiteLLM reachable at $LITELLM_BASE_URL"
    dim "      model: ${LITELLM_MODEL:-unset}"
  else
    note_issue "LiteLLM is not reachable at $LITELLM_BASE_URL — smart tools will fail"
  fi
else
  dim "      LITELLM_BASE_URL is unset; smart tools are disabled"
fi

# ── summary ───────────────────────────────────────────────────────────

echo
if [[ ${#ISSUES[@]} -eq 0 ]]; then
  ok "no problems found"
  exit 0
fi

fail "${#ISSUES[@]} problem(s) found:"
for issue in "${ISSUES[@]}"; do
  printf '      - %s\n' "$issue"
done
exit 1
