#!/usr/bin/env bash
#
# Check for a newer release and, with confirmation, upgrade this install to it.
#
# A self-hosted install is a checkout of this repository whose stack is built
# from source (deploy/docker-compose.yml builds the images locally). Upgrading
# is therefore: fetch the new tag, check it out, and rebuild — which is what
# this does, after saying what will change and asking. Configuration lives in
# deploy/.env and the database, neither tracked by git, so nothing you set is
# touched.
#
# Usage:
#   scripts/upgrade.sh              check, then upgrade if you confirm
#   scripts/upgrade.sh --check      only report whether an update is available
#   scripts/upgrade.sh --yes        upgrade without the confirmation prompt
#
# On Kubernetes, upgrading is a chart or image-tag bump instead — see
# docs/environments.md.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPO="emrezdemir/repo-mcp"

CHECK_ONLY=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --check)   CHECK_ONLY=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

need curl "the update check reads the GitHub releases API over HTTPS." || exit 1

# A >= B, comparing dotted versions. `sort -V` orders them; if B sorts first,
# A is at least B. Equal is handled before the sort.
version_ge() {
  [[ "$1" == "$2" ]] && return 0
  [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" == "$2" ]]
}

CURRENT="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"

# The latest published release, without depending on jq: the tag_name line is
# the one thing needed, and grep + sed reads it. A repository with no releases
# yet returns a "Not Found" body with no tag_name, which is reported as such.
release_json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || true)"
# `|| true` on the pipeline, not just the curl: with no releases published the
# body has no tag_name, grep exits 1, and under `set -e` with `pipefail` the
# assignment itself ends the script — silently, exit 1, before reaching the
# check below that exists to explain precisely this. Which is what happened
# the first time a tag was pushed and no Release object had been created.
LATEST="$(grep -m1 '"tag_name"' <<<"$release_json" \
  | sed -E 's/.*"tag_name":[[:space:]]*"v?([^"]+)".*/\1/' || true)"

if [[ -z "$LATEST" ]]; then
  die "could not read the latest release from GitHub — offline, rate-limited, or none is published yet."
fi

if version_ge "$CURRENT" "$LATEST"; then
  ok "up to date — v$CURRENT is the latest release"
  exit 0
fi

log "update available: ${C_DIM}v${CURRENT}${C_RESET} -> ${C_GREEN}v${LATEST}${C_RESET}"
dim "      release notes: https://github.com/$REPO/releases/tag/v$LATEST"

if (( CHECK_ONLY )); then
  exit 0
fi

# From here the upgrade changes the checkout, so refuse anything that would lose
# work: a non-git install, or a tree with uncommitted changes.
git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1 \
  || die "this is not a git checkout. Pull the new images instead — see docs/deployment.md."
if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
  die "you have uncommitted changes. Commit or stash them, then run this again."
fi

if (( ! ASSUME_YES )); then
  printf '\n'
  read -r -p "Upgrade to v$LATEST now? This rebuilds and restarts the stack. [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || die "aborted — nothing changed"
fi

log "fetching v$LATEST"
git -C "$REPO_ROOT" fetch --tags --quiet origin || die "git fetch failed"
git -C "$REPO_ROOT" checkout --quiet "v$LATEST" \
  || die "could not check out v$LATEST (is the tag present on origin?)"

log "rebuilding and restarting the stack"
# stack.sh up rebuilds the images, recreates the containers, and the init
# container applies any new migrations before the services start.
"$REPO_ROOT/scripts/stack.sh" up

ok "upgraded to v$LATEST"
dim "      'make debug' checks the running stack; 'scripts/upgrade.sh --check' confirms the version"
