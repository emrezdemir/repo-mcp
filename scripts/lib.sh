#!/usr/bin/env bash
# Shared helpers for the scripts in this directory. Not executable on its own.

set -euo pipefail

if [[ -t 1 ]] && [[ "${NO_COLOR:-}" == "" ]]; then
  C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_DIM=$'\033[2m'
else
  C_RESET=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_DIM=''
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT

log()   { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()    { printf '%s  ok%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%swarn%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail()  { printf '%sfail%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
dim()   { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

die() { fail "$*"; exit 1; }

# Fails with an actionable message rather than "command not found".
need() {
  local cmd="$1" hint="${2:-}"
  command -v "$cmd" >/dev/null 2>&1 && return 0
  fail "$cmd is required but not installed."
  [[ -n "$hint" ]] && dim "      $hint"
  return 1
}

# Track failures without aborting, so a check script reports everything at once
# instead of stopping at the first problem.
CHECKS_FAILED=0
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    ok "$label"
  else
    fail "$label"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
  fi
}

# Resolve the Python interpreter for a service, preferring its local venv.
py_for() {
  local service="$1"
  if [[ -x "$REPO_ROOT/$service/.venv/bin/python" ]]; then
    echo "$REPO_ROOT/$service/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    echo "python3"
  else
    echo "python"
  fi
}

# Wait until a URL answers, or give up. Used by the smoke and e2e scripts so
# they do not race a container that is still starting.
wait_for_http() {
  local url="$1" timeout="${2:-60}" label="${3:-$1}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then
      ok "$label is up"
      return 0
    fi
    sleep 1
  done
  fail "$label did not become ready within ${timeout}s ($url)"
  return 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$REPO_ROOT/deploy/docker-compose.yml" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$REPO_ROOT/deploy/docker-compose.yml" "$@"
  else
    die "docker compose is required (install Docker Desktop or the compose plugin)"
  fi
}
