#!/usr/bin/env bash
#
# The project's version lives in one file, VERSION. Everything else — the three
# Python packages, the Helm chart, the READMEs — is derived from it, and this
# script is what derives them.
#
# Five copies of a version number kept in step by hand is five chances to ship
# a chart that deploys an image it does not match. `--check` is the gate; it
# runs in `make verify` and in CI.
#
# Usage:
#   scripts/version.sh                    print the current version
#   scripts/version.sh --check            fail if anything disagrees with VERSION
#   scripts/version.sh --set 1.2.3        set it everywhere
#   scripts/version.sh --bump patch       0.1.0 → 0.1.1
#   scripts/version.sh --bump minor       0.1.0 → 0.2.0
#   scripts/version.sh --bump major       0.1.0 → 1.0.0
#
# Bumping does not commit, tag or push. Read the diff first.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

VERSION_FILE="$REPO_ROOT/VERSION"
[[ -f "$VERSION_FILE" ]] || die "no VERSION file at $VERSION_FILE"

CURRENT="$(tr -d '[:space:]' < "$VERSION_FILE")"

# Every file that carries the version, and the pattern that finds it. Adding a
# sixth place means adding it here — and then --check enforces it forever.
declare -a TARGETS=(
  "common/pyproject.toml|^version = \"|\"|toml"
  "gateway/pyproject.toml|^version = \"|\"|toml"
  "indexer/pyproject.toml|^version = \"|\"|toml"
  "deploy/helm/repo-mcp/Chart.yaml|^version: ||chart"
  "deploy/helm/repo-mcp/Chart.yaml|^appVersion: \"|\"|chart-app"
)

read_value() {
  local file="$1" prefix="$2" suffix="$3"
  local line
  line="$(grep -m1 -- "$prefix" "$REPO_ROOT/$file" 2>/dev/null || true)"
  [[ -z "$line" ]] && { echo ""; return; }
  line="${line#"${prefix#^}"}"
  [[ -n "$suffix" ]] && line="${line%"$suffix"}"
  echo "$line" | tr -d '[:space:]'
}

write_value() {
  local file="$1" prefix="$2" suffix="$3" value="$4"
  local bare="${prefix#^}"
  # The prefix is a literal, so anchor on it and replace the rest of the line.
  python3 - "$REPO_ROOT/$file" "$bare" "$suffix" "$value" <<'PY'
import sys

path, prefix, suffix, value = sys.argv[1:5]
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
for i, line in enumerate(lines):
    if line.startswith(prefix):
        ending = "\n" if line.endswith("\n") else ""
        lines[i] = f"{prefix}{value}{suffix}{ending}"
        break
open(path, "w", encoding="utf-8").write("".join(lines))
PY
}

is_semver() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

apply() {
  local value="$1" entry file prefix suffix
  for entry in "${TARGETS[@]}"; do
    IFS='|' read -r file prefix suffix _ <<<"$entry"
    write_value "$file" "$prefix" "$suffix" "$value"
  done
  echo "$value" > "$VERSION_FILE"
  ok "version set to $value in VERSION and ${#TARGETS[@]} derived places"
  dim "      remember the READMEs and CHANGELOG.md — 'scripts/version.sh --check' will ask"
}

check() {
  local problems=0 entry file prefix suffix label actual

  for entry in "${TARGETS[@]}"; do
    IFS='|' read -r file prefix suffix label <<<"$entry"
    actual="$(read_value "$file" "$prefix" "$suffix")"
    if [[ "$actual" != "$CURRENT" ]]; then
      fail "$file ($label) says '${actual:-nothing}', VERSION says '$CURRENT'"
      problems=1
    fi
  done

  # A release that does not say what changed is not a release. The rule the
  # maintainer asked for — every version updates the documentation — is only
  # real if something checks it.
  local readme
  for readme in README.md README.en.md; do
    [[ -f "$REPO_ROOT/$readme" ]] || continue
    if ! grep -q -- "$CURRENT" "$REPO_ROOT/$readme"; then
      fail "$readme does not mention version $CURRENT"
      dim "      every release updates the READMEs; say which version they describe"
      problems=1
    fi
  done

  if ! grep -qE "^## \[?($CURRENT|Unreleased)\]?" "$REPO_ROOT/CHANGELOG.md"; then
    fail "CHANGELOG.md has neither an [Unreleased] section nor one for $CURRENT"
    problems=1
  fi

  if (( problems )); then
    echo >&2
    echo "  Fix them in one step:  scripts/version.sh --set $CURRENT" >&2
    return 1
  fi

  ok "version $CURRENT is consistent across ${#TARGETS[@]} files, the READMEs and the changelog"
}

case "${1:-}" in
  "")
    echo "$CURRENT"
    ;;
  --check)
    check
    ;;
  --set)
    [[ -n "${2:-}" ]] || die "--set needs a version, e.g. --set 1.2.3"
    is_semver "$2" || die "not a semantic version: $2"
    apply "$2"
    ;;
  --bump)
    IFS='.' read -r major minor patch <<<"$CURRENT"
    case "${2:-}" in
      major) major=$((major + 1)); minor=0; patch=0 ;;
      minor) minor=$((minor + 1)); patch=0 ;;
      patch) patch=$((patch + 1)) ;;
      *) die "--bump takes major, minor or patch" ;;
    esac
    apply "${major}.${minor}.${patch}"
    ;;
  -h|--help)
    sed -n '2,20p' "$0" | sed -E 's/^# ?//'
    ;;
  *)
    die "unknown argument: $1 (try --help)"
    ;;
esac
