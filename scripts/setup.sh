#!/usr/bin/env bash
#
# One-shot local setup: virtualenvs, dependencies, configuration files and a
# .env with freshly generated secrets. Safe to re-run — existing configuration
# is never overwritten.
#
# Usage:
#   scripts/setup.sh                everything: virtualenvs and configuration
#   scripts/setup.sh --no-venv      install into the active environment instead
#   scripts/setup.sh --config-only  configuration only, no Python at all
#
# --config-only is the one to use on a server that will run `make up`: the
# stack is entirely Docker, and the virtualenvs exist for developing and
# testing here. Without it a deployment has to install a Python toolchain to
# produce a .env file.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CREATE_VENV=1
CONFIG_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-venv) CREATE_VENV=0 ;;
    --config-only) CONFIG_ONLY=1; CREATE_VENV=0 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

need python3 "Python 3.11 or newer is required." || exit 1

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  die "Python 3.11+ is required, found $PY_VERSION"
fi
ok "python $PY_VERSION"

#: What CI actually runs the test suite against. Anything newer is allowed —
#: this is a floor, not a whitelist — but it is worth saying so, because a
#: dependency without a wheel for a brand-new interpreter fails during pip
#: with a compiler error that looks like a problem with this project.
TESTED_MAX="3.13"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] <= (3, 13) else 1)'; then
  warn "python $PY_VERSION is newer than the $TESTED_MAX that CI tests against"
  dim "      It should work. If pip fails building a dependency, that is why,"
  dim "      and a $TESTED_MAX interpreter is the quickest way around it."
fi

# ── dependencies ──────────────────────────────────────────────────────

# On Debian and Ubuntu the standard library is split up and `venv` ships
# separately, so `python3 -m venv` creates the directory and *then* fails for
# want of ensurepip. Checking here means one clear message instead of three
# copies of "./.venv/bin/pip: No such file or directory".
if (( CREATE_VENV )) && ! python3 -c 'import ensurepip' 2>/dev/null; then
  fail "python $PY_VERSION cannot create virtual environments: ensurepip is missing."
  dim "      Debian/Ubuntu split it into its own package:"
  dim "          sudo apt install python3-venv     # or python${PY_VERSION}-venv"
  dim "      Then run 'make setup' again. To use the environment you are already"
  dim "      in instead, run 'scripts/setup.sh --no-venv'."
  exit 1
fi

# Creates $1/.venv, or explains why it could not.
#
# The test is the pip binary rather than the directory: a half-made virtualenv
# left behind by an earlier failure would otherwise be mistaken for a finished
# one, and re-running would fail identically forever. That is exactly what
# happened before this function existed.
make_venv() {
  local service="$1"
  [[ -x .venv/bin/pip ]] && return 0

  if [[ -e .venv ]]; then
    warn "$service/.venv exists but has no pip in it; rebuilding"
    rm -rf .venv
  fi

  python3 -m venv .venv || die "could not create $service/.venv (see the error above)"
  [[ -x .venv/bin/pip ]] \
    || die "$service/.venv was created without pip; install python3-venv and retry"
}

if (( CONFIG_ONLY )); then
  dim "      skipping dependencies (--config-only)"
else
  for service in common gateway indexer; do
    log "setting up $service"
    cd "$REPO_ROOT/$service" || die "cannot enter $service"
    if (( CREATE_VENV )); then
      make_venv "$service"
      ./.venv/bin/pip install --quiet --upgrade pip \
        || die "could not upgrade pip in $service/.venv"
      # gateway and indexer depend on repo-mcp-common, a sibling package that is
      # not published to any index. The path is declared in [tool.uv.sources],
      # which only uv reads — pip ignores it, looks for repo-mcp-common on PyPI
      # and fails with "No matching distribution found". Installing the local
      # copy into this venv first means the dependency is already satisfied when
      # the service itself is installed, and editable so a change to common is
      # picked up here too.
      if [[ "$service" != common ]]; then
        # Pass the path with a single leading slash. On hosts where pwd reports
        # the tree as //home/... — VirtualBox shared folders and some bind
        # mounts do — an absolute path beginning with // makes pip read the //
        # as a URL authority and fail with "file:// scheme is supported only on
        # localhost". Collapsing the leading slash avoids it; on Linux //x and
        # /x are the same directory.
        common_dir="/$(printf '%s' "$REPO_ROOT/common" | sed 's#^/*##')"
        ./.venv/bin/pip install --quiet -e "$common_dir" \
          || die "could not install repo-mcp-common into $service/.venv"
      fi
      ./.venv/bin/pip install --quiet -e '.[dev]' \
        || die "could not install $service dependencies"
      ok "$service dependencies installed in $service/.venv"
    else
      python3 -m pip install --quiet -e '.[dev]' \
        || die "could not install $service dependencies"
      ok "$service dependencies installed into the active environment"
    fi
  done
  cd "$REPO_ROOT" || die "cannot enter $REPO_ROOT"
fi

# ── configuration ─────────────────────────────────────────────────────

log "preparing configuration"
for name in tenants scan; do
  target="$REPO_ROOT/deploy/$name.yaml"
  if [[ -f "$target" ]]; then
    dim "      deploy/$name.yaml already exists, left untouched"
  else
    cp "$REPO_ROOT/deploy/$name.example.yaml" "$target"
    ok "created deploy/$name.yaml from the example"
  fi
done

# ── secrets ───────────────────────────────────────────────────────────

# The pre-commit hook is what actually stops a secret reaching the remote;
# .gitignore does nothing for a file that is already tracked.
if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  "$REPO_ROOT/scripts/check-secrets.sh" --install >/dev/null && ok "pre-commit secret hook installed"
fi

# deploy/.env is written by the wizard, not here. Two generators would drift
# and then disagree about which variables the stack needs. The wizard asks when
# there is a terminal and falls back to the full bundled stack when there is
# not, so `make setup` still works unattended.
"$REPO_ROOT/scripts/wizard.sh"

# ── verification ──────────────────────────────────────────────────────

# Reading the documents with the real loaders is what makes this worth doing —
# a YAML file that parses can still be a configuration the services reject.
# That needs the dependencies, so --config-only says what it is not doing
# rather than pretending the check ran.
if (( CONFIG_ONLY )); then
  dim "      skipping configuration verification (--config-only)"
  dim "      the services validate at startup; 'make up' fails loudly if it is wrong"
else

log "verifying configuration parses"
"$(py_for gateway)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "gateway")
from app.tenants import TenantRegistry

registry = TenantRegistry.load(Path("deploy/tenants.yaml"))
print(f"  tenants: {', '.join(t.name for t in registry.tenants)}")
print(f"  roles:   {', '.join(a.role.value for a in registry.role_assignments)}")
PY

"$(py_for indexer)" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "indexer")
from app.repos import ScanConfig

config = ScanConfig.load(Path("deploy/scan.yaml"), Path("/var/lib/repo-mcp/repos"))
print(f"  connectors: {', '.join(c.name for c in config.connectors)}")
PY
ok "configuration is valid"

fi

cat <<EOF

${C_GREEN}Setup complete.${C_RESET}

Next:
  1. Edit ${C_BLUE}deploy/.env${C_RESET}       — add a provider token (GITHUB_TOKEN, ...)
  2. Edit ${C_BLUE}deploy/scan.yaml${C_RESET}  — point a connector at your org or group
  3. Edit ${C_BLUE}deploy/tenants.yaml${C_RESET} — map your LDAP groups to squads

Then:
EOF

# Suggesting scripts/test.sh to somebody who deliberately installed no Python
# packages would be a broken instruction, so the list follows the mode.
if (( CONFIG_ONLY )); then
  cat <<EOF
  ${C_DIM}make up${C_RESET}                  bring up the full Docker stack
  ${C_DIM}make smoke${C_RESET}               check it end to end

${C_DIM}Run 'make setup' without --config-only if you also want to develop or${C_RESET}
${C_DIM}test here; that is what the virtualenvs are for.${C_RESET}
EOF
else
  cat <<EOF
  ${C_DIM}scripts/test.sh${C_RESET}          run tests and linting
  ${C_DIM}scripts/dev.sh${C_RESET}           run both services locally, no Docker
  ${C_DIM}scripts/stack.sh up${C_RESET}      bring up the full Docker stack
  ${C_DIM}scripts/debug.sh${C_RESET}         diagnose a running or broken setup

${C_DIM}Branching: develop on ${C_RESET}dev${C_DIM}. See docs/development.md.${C_RESET}
EOF
fi
