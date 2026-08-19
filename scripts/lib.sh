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
# Collapse a leading double slash. Some mounts — VirtualBox shared folders in
# particular — make pwd report the tree as //home/... . On Linux //x and /x are
# the same directory, but the two slashes leak into everything downstream and
# break tools that do not agree they are equal: pip reads the // as a URL
# authority ("file:// scheme is supported only on localhost"), and pytest's
# summary calls pathlib's relative_to(), which raises because //home/... is not
# under /home/... . One slash, once, here, fixes all of it.
REPO_ROOT="/$(printf '%s' "$REPO_ROOT" | sed 's#^/*##')"
export REPO_ROOT

# Every script runs from the repository root, whatever directory it was invoked
# from. Several of them embed Python that reads "deploy/tenants.yaml" and puts
# "gateway" on sys.path — relative paths, which silently mean something else
# when the caller is somewhere in the tree. Run from scripts/, dev.sh died with
# FileNotFoundError, and debug.sh did worse: it reported "tenants.yaml is
# invalid" one line after confirming the file exists, which sends whoever reads
# it off to edit a file that was fine. Nothing here uses the caller's directory
# for anything, so pinning it once is the fix rather than auditing each path.
cd "$REPO_ROOT" || { printf 'cannot enter %s\n' "$REPO_ROOT" >&2; exit 1; }

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

# ── container engine ──────────────────────────────────────────────────
# Docker or Podman, whichever is installed — both speak the same CLI and the
# same compose surface, so the scripts do not care which is underneath. Force
# one with CONTAINER_ENGINE=docker|podman; otherwise docker is preferred and
# podman is the fallback.
container_engine() {
  if [[ -n "${CONTAINER_ENGINE:-}" ]]; then
    printf '%s' "$CONTAINER_ENGINE"
  elif command -v docker >/dev/null 2>&1; then
    printf 'docker'
  elif command -v podman >/dev/null 2>&1; then
    printf 'podman'
  else
    printf 'docker'  # so a missing-engine message names the common one
  fi
}

# The engine itself, for a direct build/push/exec that is not a compose command.
container() { "$(container_engine)" "$@"; }

# Fail with an actionable message if the chosen engine is not installed.
need_container_engine() {
  local engine
  engine="$(container_engine)"
  command -v "$engine" >/dev/null 2>&1 && return 0
  fail "$engine is required but not installed."
  dim "      install Docker (https://docs.docker.com/get-docker/) or Podman"
  dim "      (https://podman.io/), or set CONTAINER_ENGINE to the one you have."
  return 1
}

# True if a compose implementation is available for the chosen engine. Used to
# decide whether a check can run, rather than failing when it cannot.
have_compose() {
  case "$(container_engine)" in
    docker) docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 ;;
    podman) podman compose version >/dev/null 2>&1 || command -v podman-compose >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Run a compose subcommand against the stack file, on whichever engine is
# present: `docker compose`/`docker-compose`, or `podman compose`/`podman-compose`.
compose() {
  local file="$REPO_ROOT/deploy/docker-compose.yml"
  case "$(container_engine)" in
    docker)
      if docker compose version >/dev/null 2>&1; then
        docker compose -f "$file" "$@"
      elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$file" "$@"
      else
        die "docker compose is required (install Docker Desktop or the compose plugin), or set CONTAINER_ENGINE=podman"
      fi
      ;;
    podman)
      if podman compose version >/dev/null 2>&1; then
        podman compose -f "$file" "$@"
      elif command -v podman-compose >/dev/null 2>&1; then
        podman-compose -f "$file" "$@"
      else
        die "podman compose is required (install podman-compose, or podman 4.1+ with its compose plugin)"
      fi
      ;;
    *)
      die "unknown CONTAINER_ENGINE '$(container_engine)' — use docker or podman"
      ;;
  esac
}
