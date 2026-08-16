#!/usr/bin/env bash
#
# Assemble the project site into _site/.
#
# The landing pages live in site/ and the screenshots in docs/images/ — one
# copy, used by the READMEs and by the site both. This puts them at the root,
# so nothing is duplicated in git and a local preview is the same thing GitHub
# Pages publishes.
#
# The reference documentation is built from docs/*.md by Docusaurus in
# docs-site/. The markdown stays the single source: docs-site/scripts/
# sync-docs.mjs copies it in and rewrites the links that cannot be pages here.
# The landing sits at /, the documentation under /docs.
#
# Usage:
#   scripts/build-site.sh            assemble into _site/
#   scripts/build-site.sh --serve    assemble, then serve it on :8000

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVE=0
case "${1:-}" in
  --serve) SERVE=1 ;;
  -h|--help) sed -n '2,20p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac

need node "Docusaurus builds the documentation. Install Node 18+ (nodejs.org)." || exit 1

OUT="$REPO_ROOT/_site"
rm -rf "$OUT"
mkdir -p "$OUT/images"

cp "$REPO_ROOT"/site/*.html "$REPO_ROOT"/site/*.css "$REPO_ROOT"/site/*.svg "$OUT/"
cp "$REPO_ROOT"/docs/images/* "$OUT/images/"

# ── the documentation ─────────────────────────────────────────────────
# Docusaurus, in its own directory with its own toolchain. npm ci wants a
# lockfile and a clean tree; fall back to install for a first local run where
# neither is present yet.

SITE="$REPO_ROOT/docs-site"
if [[ ! -d "$SITE/node_modules" ]]; then
  if [[ -f "$SITE/package-lock.json" ]]; then
    log "installing documentation site dependencies (npm ci)"
    npm --prefix "$SITE" ci || die "npm ci failed in docs-site/"
  else
    log "installing documentation site dependencies (npm install)"
    npm --prefix "$SITE" install || die "npm install failed in docs-site/"
  fi
fi

log "building the documentation with Docusaurus"
npm --prefix "$SITE" run build || die "Docusaurus build failed"
cp -r "$SITE/build" "$OUT/docs"

# Jekyll would otherwise try to process this and drop anything beginning with
# an underscore. There is nothing here for it to do.
touch "$OUT/.nojekyll"

ok "assembled $(find "$OUT" -type f | wc -l | tr -d ' ') files into _site/"

if (( SERVE )); then
  # The documentation is built with baseUrl /repo-mcp/docs/, so it only renders
  # correctly under that path. This serves the landing; for the docs alone,
  # `npm --prefix docs-site run serve` is the faithful preview.
  log "serving http://127.0.0.1:8000 — Ctrl-C to stop"
  cd "$OUT" && exec python3 -m http.server 8000
fi
