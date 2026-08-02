#!/usr/bin/env bash
#
# Check or update the browser libraries committed under gateway/app/ui/vendor.
#
# They are committed rather than installed by a package manager: three files
# that change a few times a year do not justify a lockfile, a Node stage in the
# image and a second dependency ecosystem to keep patched. This script is what
# keeps "committed" from meaning "forgotten".
#
# Usage:
#   scripts/update-vendor.sh           report the pinned and latest versions
#   scripts/update-vendor.sh --apply   download the pinned versions and verify
#   scripts/update-vendor.sh --verify  check the files against checksums.txt
#
# To move to a new version, edit PINNED below, run --apply, then load /ui and
# draw a graph. A renderer change is not something the test suite can catch.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

VENDOR="$REPO_ROOT/gateway/app/ui/vendor"
SUMS="$VENDOR/checksums.txt"
REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"

# package|version|path inside the tarball|file name here
PINNED=(
  "sigma|3.0.3|package/dist/sigma.min.js|sigma.min.js"
  "graphology|0.26.0|package/dist/graphology.umd.min.js|graphology.umd.min.js"
  "graphology-library|0.8.0|package/dist/graphology-library.min.js|graphology-library.min.js"
)

MODE=report
case "${1:-}" in
  --apply)  MODE=apply ;;
  --verify) MODE=verify ;;
  -h|--help) sed -n '2,18p' "$0" | sed 's/^# \?//'; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac

need curl || exit 1

latest_version() {
  curl -fsSL "$REGISTRY/$1" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["dist-tags"]["latest"])' 2>/dev/null \
    || echo "?"
}

# ── verify ────────────────────────────────────────────────────────────

if [[ "$MODE" == verify ]]; then
  [[ -f "$SUMS" ]] || die "no checksums.txt — run scripts/update-vendor.sh --apply"
  if (cd "$VENDOR" && sha256sum -c --quiet checksums.txt); then
    ok "vendored files match checksums.txt"
    exit 0
  fi
  fail "a vendored file does not match checksums.txt"
  dim "      either it was edited by hand, which it should not be, or the"
  dim "      checksum was not updated after a deliberate change"
  exit 1
fi

# ── report ────────────────────────────────────────────────────────────

if [[ "$MODE" == report ]]; then
  printf '  %-28s %-10s %-10s %s\n' PACKAGE PINNED LATEST STATUS
  outdated=0
  for entry in "${PINNED[@]}"; do
    IFS='|' read -r package version _ file <<<"$entry"
    newest="$(latest_version "$package")"
    if [[ ! -f "$VENDOR/$file" ]]; then
      state="MISSING"
    elif [[ "$newest" == "$version" || "$newest" == "?" ]]; then
      state="current"
    else
      state="update available"
      outdated=1
    fi
    printf '  %-28s %-10s %-10s %s\n' "$package" "$version" "$newest" "$state"
  done
  echo
  if (( outdated )); then
    dim "      edit PINNED in this script, then run --apply"
  fi
  exit 0
fi

# ── apply ─────────────────────────────────────────────────────────────

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$VENDOR"

for entry in "${PINNED[@]}"; do
  IFS='|' read -r package version path file <<<"$entry"
  log "$package $version"

  tarball="$REGISTRY/$package/-/${package}-${version}.tgz"
  curl -fsSL "$tarball" -o "$work/$package.tgz" \
    || die "cannot download $tarball"

  tar -xzf "$work/$package.tgz" -C "$work" \
    || die "cannot unpack $package"

  [[ -f "$work/$path" ]] \
    || die "$package $version has no $path — the published layout changed"

  # The licence travels with the file; NOTICE points at it.
  install -m 0644 "$work/$path" "$VENDOR/$file"
  rm -rf "$work/package"
  ok "$file"
done

(cd "$VENDOR" && sha256sum ./*.js > checksums.txt)
ok "wrote checksums.txt"

cat >&2 <<EOF

${C_BLUE}Next${C_RESET}
  1. Update the version table in gateway/app/ui/vendor/README.md
  2. Load ${C_BLUE}/ui${C_RESET}, draw a graph, and check that the layout still runs
  3. ${C_BLUE}make verify${C_RESET}

EOF
