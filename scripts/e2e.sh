#!/usr/bin/env bash
#
# Full end-to-end run: build the images, start the stack, index a real
# repository, query it through MCP, then tear down.
#
# This is the check to run before tagging a release — it exercises the paths
# unit tests deliberately do not: the engine binary, the stdio bridge, git
# cloning and the container images themselves.
#
# Usage:
#   scripts/e2e.sh              build, test, tear down
#   scripts/e2e.sh --keep       leave the stack running afterwards
#   scripts/e2e.sh --no-build   reuse existing images

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_container_engine || exit 1
need curl || exit 1
need jq || exit 1

KEEP=0
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --keep)     KEEP=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help)  sed -n '2,13p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

WORK_DIR="$(mktemp -d)"
STACK_STARTED=0

# This run needs its own tenant, connector and secrets, which means writing
# over deploy/*.yaml and deploy/.env. Those may be a real setup, so they are
# moved aside first and put back unconditionally on the way out.
MANAGED_FILES=(deploy/tenants.yaml deploy/scan.yaml deploy/.env)

stash_config() {
  for relative in "${MANAGED_FILES[@]}"; do
    if [[ -f "$REPO_ROOT/$relative" ]]; then
      mkdir -p "$WORK_DIR/backup/$(dirname "$relative")"
      cp -p "$REPO_ROOT/$relative" "$WORK_DIR/backup/$relative"
    fi
  done
  ok "existing configuration stashed in $WORK_DIR/backup"
}

restore_config() {
  for relative in "${MANAGED_FILES[@]}"; do
    if [[ -f "$WORK_DIR/backup/$relative" ]]; then
      cp -p "$WORK_DIR/backup/$relative" "$REPO_ROOT/$relative"
    else
      rm -f "$REPO_ROOT/$relative"
    fi
  done
}

cleanup() {
  local status=$?
  if (( STACK_STARTED )) && (( ! KEEP )); then
    log "tearing down"
    compose down -v >/dev/null 2>&1 || true
  elif (( STACK_STARTED )); then
    warn "stack left running (--keep); stop it with scripts/stack.sh down"
  fi

  if (( KEEP )); then
    # The running containers bind-mount these files; putting the originals
    # back now would change what they see mid-flight.
    warn "your configuration is NOT restored while the stack is up"
    dim "      backup:  $WORK_DIR/backup"
    dim "      restore: cp -a $WORK_DIR/backup/deploy/. $REPO_ROOT/deploy/"
  else
    restore_config
    rm -rf "$WORK_DIR"
  fi
  exit $status
}
trap cleanup EXIT INT TERM

# ── configuration ─────────────────────────────────────────────────────

log "preparing an isolated configuration"
stash_config

# A self-contained tenant so the run does not depend on whatever the developer
# has in deploy/tenants.yaml.
cat > "$REPO_ROOT/deploy/tenants.yaml" <<'EOF'
roles:
  admin: [e2e-admins]
tenants:
  e2e:
    ldap_groups: [e2e-admins]
    tool_profile: all
    projects: ["*"]
EOF

cat > "$REPO_ROOT/deploy/scan.yaml" <<'EOF'
connectors:
  - name: e2e-placeholder
    type: github
    org: pallets
    token_env: GITHUB_TOKEN
    tenant: e2e
    include: ["click"]
    mode: fast
EOF

E2E_TOKEN="e2e-$(date +%s)"
cat > "$REPO_ROOT/deploy/.env" <<EOF
LITELLM_MASTER_KEY=e2e-master-key
CI_TRIGGER_TOKEN=$E2E_TOKEN
KEYCLOAK_ADMIN_PASSWORD=e2e-admin
WEBHOOK_SECRET_GITHUB=e2e-webhook
DEV_INSECURE_AUTH=true
DEV_STATIC_TOKEN=$E2E_TOKEN
DEV_STATIC_GROUPS=e2e-admins
SMART_TOOLS_ENABLED=false
GITHUB_TOKEN=${GITHUB_TOKEN:-}
CBM_VERSION=${CBM_VERSION:-latest}
INDEX_CONCURRENCY=1
EOF
ok "configuration written"

# ── stack ─────────────────────────────────────────────────────────────

log "starting the stack"
STACK_STARTED=1
if (( BUILD )); then
  compose up -d --build gateway indexer
else
  compose up -d gateway indexer
fi

wait_for_http "http://127.0.0.1:8080/healthz" 180 "gateway" || {
  compose logs --tail=50 gateway
  die "gateway never became healthy"
}
wait_for_http "http://127.0.0.1:8082/healthz" 180 "indexer" || {
  compose logs --tail=50 indexer
  die "indexer never became healthy"
}

# ── engine ────────────────────────────────────────────────────────────

log "engine inside the image"
version="$(compose exec -T gateway codebase-memory-mcp --version 2>&1 | head -1)"
ok "gateway engine: $version"
indexer_version="$(compose exec -T indexer codebase-memory-mcp --version 2>&1 | head -1)"
if [[ "$version" == "$indexer_version" ]]; then
  ok "both services run the same engine build"
else
  # A mismatch fails at runtime with a version cohort conflict, not here, so
  # catching it now saves a confusing debugging session later.
  die "engine build mismatch: gateway=$version indexer=$indexer_version"
fi

# ── index a real repository ───────────────────────────────────────────

log "indexing a real repository through the engine"
compose exec -T indexer sh -c '
  set -e
  mkdir -p /var/lib/repo-mcp/repos/e2e
  cd /var/lib/repo-mcp/repos/e2e
  [ -d click ] || git clone --depth 1 --quiet https://github.com/pallets/click.git click
  CBM_CACHE_DIR=/var/lib/repo-mcp/cache/tenant/e2e \
  CBM_ALLOWED_ROOT=/var/lib/repo-mcp/repos/e2e \
  codebase-memory-mcp cli --json index_repository \
    "{\"repo_path\":\"/var/lib/repo-mcp/repos/e2e/click\",\"mode\":\"fast\",\"name\":\"click\"}" \
    > /tmp/index.json 2>/tmp/index.err || { tail -20 /tmp/index.err; exit 1; }
  echo indexed
' || die "indexing failed"
ok "repository indexed"

# ── query through MCP ─────────────────────────────────────────────────

log "querying through the MCP gateway"

mcp() {
  curl -sS --max-time 60 http://127.0.0.1:8080/mcp \
    -H "Authorization: Bearer $E2E_TOKEN" \
    -H 'X-Tenant: e2e' \
    -H 'Content-Type: application/json' \
    -d "$1"
}

FAILED=0
expect() {
  local label="$1" condition="$2"
  if [[ "$condition" == "true" ]]; then ok "$label"; else fail "$label"; FAILED=$((FAILED+1)); fi
}

tools="$(mcp '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')"
expect "tools/list returns the full tool set" \
  "$(jq -e '(.result.tools | length) >= 10' <<<"$tools" >/dev/null && echo true || echo false)"

projects="$(mcp '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_projects","arguments":{}}}')"
expect "list_projects finds the indexed project" \
  "$(jq -r '.result.content[]?.text' <<<"$projects" | grep -qi click && echo true || echo false)"

search="$(mcp '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_graph","arguments":{"project":"click","query":"command","limit":5}}}')"
expect "search_graph returns results from the real graph" \
  "$(jq -r '.result.content[]?.text' <<<"$search" | grep -qiE 'command|group|option' && echo true || echo false)"

arch="$(mcp '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_architecture","arguments":{"project":"click"}}}')"
expect "get_architecture returns a summary" \
  "$([[ -n "$(jq -r '.result.content[]?.text' <<<"$arch")" ]] && echo true || echo false)"

schema="$(mcp '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_graph_schema","arguments":{"project":"click"}}}')"
expect "get_graph_schema reports nodes and edges" \
  "$(jq -r '.result.content[]?.text' <<<"$schema" | grep -qiE 'function|class|file' && echo true || echo false)"

# ── the engine's own guard rails ──────────────────────────────────────

log "engine confinement"
escape="$(mcp '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"index_repository","arguments":{"repo_path":"/etc"}}}')"
expect "indexing outside the tenant root is refused" \
  "$(jq -e '.error.code == -32001' <<<"$escape" >/dev/null && echo true || echo false)"

# ── observability ─────────────────────────────────────────────────────

log "metrics"
expect "gateway metrics record the tool calls just made" \
  "$(curl -fsS http://127.0.0.1:8080/metrics | grep -q 'repo_mcp_tool_calls_total' && echo true || echo false)"
expect "indexer exposes metrics" \
  "$(curl -fsS http://127.0.0.1:8082/metrics | grep -q 'repo_mcp_' && echo true || echo false)"

# ── audit ─────────────────────────────────────────────────────────────

log "audit trail"
audit="$(compose logs --no-log-prefix gateway 2>/dev/null | grep -c '"event":"tools/call"' || echo 0)"
expect "tool calls were audited (found $audit records)" \
  "$([[ "$audit" -gt 0 ]] && echo true || echo false)"

echo
if (( FAILED == 0 )); then
  ok "end-to-end run passed"
  exit 0
fi
fail "$FAILED end-to-end assertion(s) failed"
compose logs --tail=40 gateway indexer
exit 1
