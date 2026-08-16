#!/usr/bin/env bash
#
# End-to-end smoke test against a running stack: index a real repository, then
# query the graph through the MCP endpoint and assert the answers are sane.
#
# Every assertion is one observable behaviour, so a failure names the thing
# that broke rather than "smoke test failed".
#
# Usage:
#   scripts/smoke.sh                          against the local dev services
#   scripts/smoke.sh --docker                 against the Docker stack
#   scripts/smoke.sh --repo URL --name NAME   index a specific repository
#
# Environment:
#   GATEWAY_URL, INDEXER_URL, DEV_STATIC_TOKEN, TENANT

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need curl || exit 1
need jq "smoke assertions need jq" || exit 1

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
INDEXER_URL="${INDEXER_URL:-http://127.0.0.1:8082}"
TOKEN="${DEV_STATIC_TOKEN:-devtoken}"
TENANT="${TENANT:-}"
# Small, permissively licensed and stable — indexes in seconds.
SAMPLE_REPO="${SAMPLE_REPO:-https://github.com/pallets/click}"
SAMPLE_NAME="${SAMPLE_NAME:-smoke-click}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) GATEWAY_URL=http://127.0.0.1:8080; INDEXER_URL=http://127.0.0.1:8082 ;;
    --repo)   SAMPLE_REPO="$2"; shift ;;
    --name)   SAMPLE_NAME="$2"; shift ;;
    --tenant) TENANT="$2"; shift ;;
    --token)  TOKEN="$2"; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

# shellcheck disable=SC1091
[[ -f "$REPO_ROOT/deploy/.env" ]] && set -a && source "$REPO_ROOT/deploy/.env" && set +a

PASSED=0
FAILED=0

assert() {
  local label="$1" condition="$2"
  if [[ "$condition" == "true" ]]; then
    ok "$label"
    PASSED=$((PASSED + 1))
  else
    fail "$label"
    FAILED=$((FAILED + 1))
  fi
}

mcp() {
  local method="$1" params="${2:-{\}}"
  local headers=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json')
  [[ -n "$TENANT" ]] && headers+=(-H "X-Tenant: $TENANT")
  curl -sS --max-time 180 "$GATEWAY_URL/mcp" "${headers[@]}" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$method\",\"params\":$params}"
}

call_tool() {
  mcp "tools/call" "{\"name\":\"$1\",\"arguments\":$2}"
}

# Tool results are MCP content blocks; the text part is what we assert on.
tool_text() { jq -r '.result.content[]? | select(.type=="text") | .text' <<<"$1"; }

# ── 1. reachability ───────────────────────────────────────────────────

log "reachability"
wait_for_http "$GATEWAY_URL/healthz" 30 "gateway" || die "gateway is down"
wait_for_http "$INDEXER_URL/healthz" 30 "indexer" || die "indexer is down"

# ── 2. protocol handshake ─────────────────────────────────────────────

log "MCP handshake"
init="$(mcp initialize '{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}')"
assert "initialize returns a protocol version" \
  "$(jq -e 'has("result") and (.result.protocolVersion | type == "string")' <<<"$init" >/dev/null && echo true || echo false)"
assert "initialize advertises the tools capability" \
  "$(jq -e '.result.capabilities.tools' <<<"$init" >/dev/null && echo true || echo false)"

tools="$(mcp "tools/list")"
tool_names="$(jq -r '.result.tools[]?.name' <<<"$tools" | sort | tr '\n' ' ')"
assert "tools/list returns tools" \
  "$([[ -n "$tool_names" ]] && echo true || echo false)"
dim "      $tool_names"

assert "search_graph is exposed" \
  "$(grep -q search_graph <<<"$tool_names" && echo true || echo false)"

# ── 3. authorization ──────────────────────────────────────────────────

log "authorization"
unauth_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$GATEWAY_URL/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')"
assert "a request without a token is rejected with 401" \
  "$([[ "$unauth_status" == "401" ]] && echo true || echo false)"

bad_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$GATEWAY_URL/mcp" \
  -H 'Authorization: Bearer definitely-not-valid' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')"
assert "a request with a bad token is rejected" \
  "$([[ "$bad_status" == "401" || "$bad_status" == "403" ]] && echo true || echo false)"

denied="$(call_tool "search_graph" '{"project":"definitely-not-allowed","query":"x"}')"
assert "a project outside the allowlist is denied" \
  "$(jq -e '.error.code == -32001' <<<"$denied" >/dev/null && echo true || echo false)"

unknown="$(mcp "does/not/exist")"
assert "an unknown method returns -32601" \
  "$(jq -e '.error.code == -32601' <<<"$unknown" >/dev/null && echo true || echo false)"

# ── 4. indexing ───────────────────────────────────────────────────────

log "indexing $SAMPLE_REPO"
index_response="$(curl -sS --max-time 30 -X POST "$INDEXER_URL/trigger" \
  -H "Authorization: Bearer ${CI_TRIGGER_TOKEN:-}" \
  -H 'Content-Type: application/json' \
  -d "{\"repository\": \"$SAMPLE_NAME\"}" 2>/dev/null || echo '{}')"

if jq -e '.queued == true' <<<"$index_response" >/dev/null 2>&1; then
  ok "indexing queued through the indexer"
  log "waiting for the index to finish"
  for _ in $(seq 1 60); do
    projects="$(call_tool "list_projects" '{}')"
    if grep -qi "$SAMPLE_NAME" <<<"$(tool_text "$projects")"; then break; fi
    sleep 5
  done
else
  # The sample repository is usually not in scan.yaml, which is fine: the point
  # of this section is to prove the query path works against *something*.
  dim "      $SAMPLE_NAME is not a configured repository; using whatever is indexed"
fi

projects="$(call_tool "list_projects" '{}')"
projects_text="$(tool_text "$projects")"
assert "list_projects succeeds" \
  "$(jq -e '.result != null and (.result.isError | not)' <<<"$projects" >/dev/null && echo true || echo false)"

FIRST_PROJECT="$(grep -oE '[A-Za-z0-9._-]{3,}' <<<"$projects_text" | head -1 || true)"
if [[ -z "$FIRST_PROJECT" ]]; then
  warn "no indexed project found; skipping the query assertions"
  warn "index something first: curl -X POST $INDEXER_URL/rescan -H \"Authorization: Bearer \$CI_TRIGGER_TOKEN\""
else
  dim "      querying project: $FIRST_PROJECT"

  # ── 5. queries ──────────────────────────────────────────────────────

  log "graph queries"
  schema="$(call_tool "get_graph_schema" "{\"project\":\"$FIRST_PROJECT\"}")"
  assert "get_graph_schema returns content" \
    "$([[ -n "$(tool_text "$schema")" ]] && echo true || echo false)"

  search="$(call_tool "search_graph" "{\"project\":\"$FIRST_PROJECT\",\"query\":\"main\",\"limit\":5}")"
  assert "search_graph returns content" \
    "$([[ -n "$(tool_text "$search")" ]] && echo true || echo false)"

  architecture="$(call_tool "get_architecture" "{\"project\":\"$FIRST_PROJECT\"}")"
  assert "get_architecture returns content" \
    "$([[ -n "$(tool_text "$architecture")" ]] && echo true || echo false)"
fi

# ── 6. observability ──────────────────────────────────────────────────

log "observability"
metrics="$(curl -fsS --max-time 10 "$GATEWAY_URL/metrics" 2>/dev/null || true)"
assert "gateway exposes Prometheus metrics" \
  "$(grep -q 'repo_mcp_' <<<"$metrics" && echo true || echo false)"

indexer_metrics="$(curl -fsS --max-time 10 "$INDEXER_URL/metrics" 2>/dev/null || true)"
assert "indexer exposes Prometheus metrics" \
  "$(grep -q 'repo_mcp_' <<<"$indexer_metrics" && echo true || echo false)"

# ── summary ───────────────────────────────────────────────────────────

echo
if (( FAILED == 0 )); then
  ok "$PASSED assertion(s) passed"
  exit 0
fi
fail "$FAILED of $((PASSED + FAILED)) assertion(s) failed"
exit 1
