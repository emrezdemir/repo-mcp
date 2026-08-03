#!/usr/bin/env bash
#
# Run linting and tests for both services.
#
# Usage:
#   scripts/test.sh                 lint + tests for gateway and indexer
#   scripts/test.sh gateway         one service only (common|gateway|indexer)
#   scripts/test.sh --lint          linting only
#   scripts/test.sh --no-lint       tests only
#   scripts/test.sh --fix           apply lint autofixes, then run
#   scripts/test.sh --cov           with coverage report
#
# Extra arguments after -- go to pytest:
#   scripts/test.sh gateway -- -k authorization -vv

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVICES=()
RUN_LINT=1
RUN_TESTS=1
FIX=0
COVERAGE=0
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    common|gateway|indexer) SERVICES+=("$1") ;;
    --lint)     RUN_TESTS=0 ;;
    --no-lint)  RUN_LINT=0 ;;
    --fix)      FIX=1 ;;
    --cov)      COVERAGE=1 ;;
    --)         shift; PYTEST_ARGS=("$@"); break ;;
    -h|--help)  sed -n '2,16p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)          die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

[[ ${#SERVICES[@]} -eq 0 ]] && SERVICES=(common gateway indexer)

FAILURES=()

for service in "${SERVICES[@]}"; do
  cd "$REPO_ROOT/$service" || die "cannot enter $service"
  python="$(py_for "$service")"
  venv_bin="$(dirname "$python")"

  if [[ ! -x "$REPO_ROOT/$service/.venv/bin/python" ]]; then
    warn "$service has no .venv — run scripts/setup.sh for an isolated environment"
  fi

  if (( RUN_LINT )); then
    log "$service: lint"
    if [[ -x "$venv_bin/ruff" ]]; then ruff_bin="$venv_bin/ruff"
    elif command -v ruff >/dev/null 2>&1; then ruff_bin="ruff"
    else
      warn "ruff is not installed; skipping lint for $service"
      ruff_bin=""
    fi

    if [[ -n "$ruff_bin" ]]; then
      if (( FIX )); then
        "$ruff_bin" check --fix . || true
        "$ruff_bin" format . >/dev/null || true
      fi
      if "$ruff_bin" check --output-format=concise .; then
        ok "$service lint clean"
      else
        FAILURES+=("$service lint")
      fi
    fi
  fi

  if (( RUN_TESTS )); then
    log "$service: tests"
    args=(-q "${PYTEST_ARGS[@]}")
    if (( COVERAGE )); then
      if "$python" -c 'import pytest_cov' 2>/dev/null; then
        args=(--cov=app --cov-report=term-missing "${args[@]}")
      else
        warn "pytest-cov is not installed; running without coverage"
      fi
    fi
    if "$python" -m pytest "${args[@]}"; then
      ok "$service tests passed"
    else
      FAILURES+=("$service tests")
    fi
  fi
done

cd "$REPO_ROOT" || die "cannot enter $REPO_ROOT"

# Configuration files are part of the contract: a broken example would fail at
# container start rather than here, which is a much worse place to find out.
log "example configuration"
if "$(py_for gateway)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry

TenantRegistry.load(Path("deploy/tenants.example.yaml"))
PY
then ok "tenants.example.yaml parses"; else FAILURES+=("tenants.example.yaml"); fi

if "$(py_for indexer)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "indexer")
from app.repos import ScanConfig

ScanConfig.load(Path("deploy/scan.example.yaml"), Path("/tmp"))
PY
then ok "scan.example.yaml parses"; else FAILURES+=("scan.example.yaml"); fi

# The Compose file was unparseable for a while and nobody noticed, because
# nothing here read it. Interpolation needs values, so supply throwaway ones:
# the question is whether the file is valid, not what is in it.
#
# Checked with no profiles and with all of them. A service a profile excludes
# is still interpolated, so a mistake inside an optional service breaks the
# file even for someone who never starts it.
if have_compose; then
  # compose() runs whichever engine is present (docker or podman); the throwaway
  # values are exported in a subshell so they reach the compose child.
  compose_check() {
    (
      export COMPOSE_PROFILES="$1" \
        POSTGRES_PASSWORD=check SECRETS_KEY=check \
        KEYCLOAK_ADMIN_PASSWORD=check LITELLM_MASTER_KEY=check
      compose config --quiet
    )
  }
  compose_ok=1
  for profiles in "" "keycloak,litellm,ollama,headroom"; do
    if ! compose_check "$profiles" >/dev/null 2>&1; then
      compose_check "$profiles" || true
      compose_ok=0
    fi
  done
  if (( compose_ok )); then
    ok "docker-compose.yml is valid, with and without the optional profiles"
  else
    FAILURES+=("docker-compose.yml")
  fi
else
  dim "      no container compose available, skipping the Compose check"
fi

# The shell scripts are part of the contract too, and CI lints them. Running
# the same check here means a warning is a local failure rather than a
# surprise on a push. Same severity as .github/workflows/ci.yml.
if [[ -x "$REPO_ROOT/common/.venv/bin/shellcheck" ]]; then
  shellcheck_bin="$REPO_ROOT/common/.venv/bin/shellcheck"
elif command -v shellcheck >/dev/null 2>&1; then
  shellcheck_bin="shellcheck"
else
  shellcheck_bin=""
fi

if [[ -n "$shellcheck_bin" ]]; then
  log "shell scripts"
  if "$shellcheck_bin" -S warning --format=gcc "$REPO_ROOT"/scripts/*.sh; then
    ok "shellcheck clean"
  else
    FAILURES+=("shellcheck")
  fi
else
  dim "      shellcheck not installed, skipping (scripts/setup.sh installs it)"
fi

# Documentation rules are checked here too, so a change that forgets a doc
# fails in the same run as one that forgets a test.
log "documentation rules"
if "$REPO_ROOT/scripts/check-docs.sh" --quiet >/dev/null 2>&1; then
  ok "documentation rules satisfied"
else
  "$REPO_ROOT/scripts/check-docs.sh" || true
  FAILURES+=("documentation rules")
fi

echo
if [[ ${#FAILURES[@]} -eq 0 ]]; then
  ok "everything passed"
  exit 0
fi

fail "failed: ${FAILURES[*]}"
exit 1
