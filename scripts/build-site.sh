#!/usr/bin/env bash
#
# Assemble the project site into _site/.
#
# The pages live in site/ and the screenshots in docs/images/ — one copy,
# used by the READMEs and by the site both. This puts them together, so
# nothing is duplicated in git and a local preview is the same thing GitHub
# Pages publishes.
#
# The reference documentation is rendered from docs/*.md by render-docs.py:
# the markdown stays the single source, and the site stops being a page that
# links out to GitHub for everything that matters.
#
# Usage:
#   scripts/build-site.sh            assemble into _site/
#   scripts/build-site.sh --serve    assemble, then serve it on :8000

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVE=0
case "${1:-}" in
  --serve) SERVE=1 ;;
  -h|--help) sed -n '2,12p' "$0" | sed 's/^# \?//'; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac

OUT="$REPO_ROOT/_site"
rm -rf "$OUT"
mkdir -p "$OUT/images"

cp "$REPO_ROOT"/site/*.html "$REPO_ROOT"/site/*.css "$REPO_ROOT"/site/*.svg "$OUT/"
cp "$REPO_ROOT"/docs/images/* "$OUT/images/"

# ── the documentation ─────────────────────────────────────────────────
# Python-Markdown is the only build dependency the site has, and it is not
# part of either service, so it lives in its own throwaway environment rather
# than in common/. Cached between runs; delete .site-venv to rebuild it.

VENV="$REPO_ROOT/.site-venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  log "creating the site build environment"
  python3 -m venv "$VENV" || die "cannot create $VENV"
fi
if ! "$VENV/bin/python" -c 'import markdown' 2>/dev/null; then
  log "installing Python-Markdown"
  "$VENV/bin/pip" install --quiet --disable-pip-version-check markdown \
    || die "cannot install markdown (no network?); the site needs it to render docs/"
fi

"$VENV/bin/python" "$REPO_ROOT/scripts/render-docs.py" "$OUT" || die "rendering docs/ failed"

# Jekyll would otherwise try to process this and drop anything beginning with
# an underscore. There is nothing here for it to do.
touch "$OUT/.nojekyll"

ok "assembled $(find "$OUT" -type f | wc -l | tr -d ' ') files into _site/"

if (( SERVE )); then
  log "serving http://127.0.0.1:8000 — Ctrl-C to stop"
  cd "$OUT" && exec python3 -m http.server 8000
fi
