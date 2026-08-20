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
    -h|--help)  sed -n '2,16p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
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
    # ${a[@]+"${a[@]}"} rather than "${a[@]}": macOS ships bash 3.2, where
    # expanding an empty array under `set -u` is a fatal "unbound variable"
    # instead of nothing. bash 4.4 fixed it, so no Linux host and no CI runner
    # shows this — and PYTEST_ARGS is empty on every ordinary run, so `make
    # test` died here before running a single test.
    args=(-q ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"})
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

# Every answer set the wizard accepts has to produce a .env that agrees with
# itself. The defect this checks for shipped: --models external --compression on
# wrote HEADROOM_UPSTREAM_URL=http://litellm:4000/v1 while leaving litellm out
# of COMPOSE_PROFILES, so headroom pointed at a container the same file told the
# stack not to start. That fails at request time, which is far from the wizard
# that caused it.
#
# The assertion is the general rule rather than that one variable: no value may
# name an optional service unless the profile that starts it is selected.
log "the wizard's answers agree with themselves"
WIZARD_TMP="$(mktemp -d)"
trap 'rm -rf "$WIZARD_TMP"' EXIT
wizard_ok=1
for models in bundled external none; do
  for compression in off on; do
    # Refused by the wizard on purpose: compression sits in front of a model
    # backend, so "on" with no backend is not an answer set.
    [[ "$compression" == on && "$models" == none ]] && continue
    env_out="$WIZARD_TMP/env-$models-$compression"
    if ! REPO_MCP_ENV_FILE="$env_out" "$REPO_ROOT/scripts/wizard.sh" --force \
        --identity dev --models "$models" --compression "$compression" \
        --database bundled --provider none >/dev/null 2>&1; then
      fail "the wizard failed for --models $models --compression $compression"
      wizard_ok=0
      continue
    fi
    profiles="$(grep -m1 '^COMPOSE_PROFILES=' "$env_out" | cut -d= -f2- || true)"
    # These hostnames only resolve when the profile of the same name is on.
    for service in litellm ollama headroom keycloak; do
      grep -E "^[A-Z_]+=.*//$service:" "$env_out" >/dev/null 2>&1 || continue
      if [[ ",$profiles," != *",$service,"* ]]; then
        fail "--models $models --compression $compression points at http://$service but does not start it"
        grep -nE "^[A-Z_]+=.*//$service:" "$env_out" | sed 's/^/        /'
        wizard_ok=0
      fi
    done
  done
done
if (( wizard_ok )); then
  ok "no generated .env names a service its profiles leave out"
else
  FAILURES+=("wizard answer sets")
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

# The web interface has its own test suite, and until now only CI ran it. That
# is exactly how a capability gate added in one session left CI's `web
# interface` job red for the whole of the next one with nobody looking: a check
# that runs somewhere you do not watch is a check you do not have.
#
# It is skipped rather than failed when Node or the dependencies are absent —
# `make setup` installs no Node, and a Python-only checkout should not be forced
# to. The skip says what to run, so it is a choice rather than an accident.
if (( RUN_TESTS )); then
  WEBUI="$REPO_ROOT/gateway/webui"
  if ! command -v npm >/dev/null 2>&1; then
    dim "      npm not installed, skipping the web interface tests"
  elif [[ ! -d "$WEBUI/node_modules" ]]; then
    dim "      web interface dependencies not installed, skipping its tests"
    dim "      install them once:  npm --prefix gateway/webui ci"
  else
    log "web interface: tests"
    if npm --prefix "$WEBUI" test; then
      ok "web interface tests passed"
    else
      FAILURES+=("web interface tests")
    fi
  fi
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
