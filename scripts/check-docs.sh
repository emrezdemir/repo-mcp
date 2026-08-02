#!/usr/bin/env bash
#
# Enforce the documentation rules in docs/code-standards.md §5.
#
# A rule nobody checks is a suggestion, and suggestions rot. Every mechanical
# rule in that document is verified here and in CI.
#
# Usage: scripts/check-docs.sh [--quiet]

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet)   QUIET=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

cd "$REPO_ROOT" || die "cannot enter $REPO_ROOT"

FAILURES=()
note() { FAILURES+=("$1"); }
pass() { (( QUIET )) || ok "$1"; }

# ── 1. required files exist ───────────────────────────────────────────

REQUIRED=(
  README.md README.tr.md AGENTS.md CLAUDE.md CONTRIBUTING.md CHANGELOG.md
  SECURITY.md CODE_OF_CONDUCT.md LICENSE NOTICE Makefile
  docs/architecture.md docs/engine.md docs/roles-and-permissions.md
  docs/deployment.md docs/scaling.md docs/development.md docs/branching.md
  docs/roadmap.md docs/code-standards.md docs/environments.md
  memory-bank/README.md memory-bank/projectbrief.md
  memory-bank/productContext.md memory-bank/systemPatterns.md
  memory-bank/techContext.md memory-bank/activeContext.md
  memory-bank/progress.md
  deploy/.env.example deploy/tenants.example.yaml deploy/scan.example.yaml
  deploy/helm/values-dev.example.yaml deploy/helm/values-production.example.yaml
)

missing=()
for file in "${REQUIRED[@]}"; do
  if [[ ! -s "$file" ]]; then
    missing+=("$file")
  fi
done
if [[ ${#missing[@]} -eq 0 ]]; then
  pass "all ${#REQUIRED[@]} required files present and non-empty"
else
  note "missing or empty: ${missing[*]}"
fi

# ── 2. internal links resolve ─────────────────────────────────────────

link_report="$(python3 - <<'PY'
import pathlib, re, sys

broken = []
for md in sorted(pathlib.Path(".").rglob("*.md")):
    if any(part in {".venv", "node_modules", ".git"} for part in md.parts):
        continue
    for match in re.finditer(r'\[[^\]]+\]\(([^)]+)\)', md.read_text(encoding="utf-8")):
        target = match.group(1).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (md.parent / target).resolve().exists():
            broken.append(f"{md}: {target}")
print("\n".join(broken))
PY
)"
if [[ -z "$link_report" ]]; then
  pass "every internal markdown link resolves"
else
  note "broken internal links:"$'\n'"$(sed 's/^/          /' <<<"$link_report")"
fi

# ── 3. AGENTS.md commands exist as make targets ───────────────────────

# The working agreement telling an agent to run a command that does not exist
# is worse than saying nothing.
targets="$(grep -oE '^[a-z][a-z0-9_-]*:' Makefile | tr -d ':' | sort -u)"
documented="$(grep -oE '`make [a-z][a-z0-9_-]*`' AGENTS.md | sed 's/`make //; s/`//' | sort -u)"

undefined=()
while IFS= read -r cmd; do
  [[ -z "$cmd" ]] && continue
  grep -qx "$cmd" <<<"$targets" || undefined+=("$cmd")
done <<< "$documented"

if [[ ${#undefined[@]} -eq 0 ]]; then
  pass "every 'make' command in AGENTS.md exists ($(grep -c . <<<"$documented") checked)"
else
  note "AGENTS.md documents make targets that do not exist: ${undefined[*]}"
fi

# ── 4. every make target is documented with ## ─────────────────────────

undocumented=()
while IFS= read -r target; do
  [[ -z "$target" ]] && continue
  grep -qE "^${target}:.*## " Makefile || undocumented+=("$target")
done <<< "$targets"

if [[ ${#undocumented[@]} -eq 0 ]]; then
  pass "every make target has a '##' description"
else
  note "make targets without a '##' description (invisible in 'make help'): ${undocumented[*]}"
fi

# ── 5. CHANGELOG has an Unreleased section ────────────────────────────

if grep -qE '^## \[Unreleased\]' CHANGELOG.md; then
  pass "CHANGELOG.md has an [Unreleased] section"
else
  note "CHANGELOG.md is missing '## [Unreleased]'"
fi

# ── 6. ADR structure ──────────────────────────────────────────────────

ADR_SECTIONS=("## Context" "## Decision" "## Rationale" "## Consequences" "## Alternatives considered")
adr_problems=()
shopt -s nullglob
for adr in docs/adr/*.md; do
  base="$(basename "$adr")"
  [[ "$base" =~ ^[0-9]{4}-[a-z0-9-]+\.md$ ]] || adr_problems+=("$base: name must be NNNN-kebab-title.md")
  grep -qE '^- \*\*Status:\*\* (Proposed|Accepted|Superseded)' "$adr" \
    || adr_problems+=("$base: missing or invalid '- **Status:**' line")
  for section in "${ADR_SECTIONS[@]}"; do
    grep -qxF "$section" "$adr" || adr_problems+=("$base: missing '$section'")
  done
  # An ADR that only lists upsides is marketing. The negative consequences are
  # the part a future reader actually needs.
  grep -qiE '^\*\*Negative' "$adr" || adr_problems+=("$base: Consequences must include a '**Negative' subsection")
done
shopt -u nullglob

if [[ ${#adr_problems[@]} -eq 0 ]]; then
  pass "all $(ls docs/adr/*.md 2>/dev/null | wc -l | tr -d ' ') ADRs have the required structure"
else
  note "ADR problems:"$'\n'"$(printf '          %s\n' "${adr_problems[@]}")"
fi

# ── 7. README documentation index is complete ─────────────────────────

index_missing=()
while IFS= read -r target; do
  [[ -z "$target" ]] && continue
  [[ -e "$target" ]] || index_missing+=("$target")
done <<< "$(sed -n '/^## Documentation/,/^## /p' README.md \
            | grep -oE '\]\((docs/[^)]+)\)' | sed 's/](//; s/)//' | sort -u)"

if [[ ${#index_missing[@]} -eq 0 ]]; then
  pass "every document in the README index exists"
else
  note "README documentation index points at missing files: ${index_missing[*]}"
fi

# ── 8. no assistant or tool attribution ───────────────────────────────

# House rule: nothing in this repository advertises which tool wrote it.
#
# This script is excluded from its own check — it necessarily contains the
# patterns it looks for, and a scanner that always reports itself is a scanner
# people learn to ignore.
attribution="$(git ls-files -z \
  | grep -zv '^scripts/check-docs\.sh$' \
  | xargs -0 grep -lniE 'co-authored-by:[[:space:]]*(claude|copilot|cursor)|generated (with|by) (claude|copilot|cursor)|🤖 generated' \
  2>/dev/null || true)"
if [[ -z "$attribution" ]]; then
  pass "no tool attribution in tracked files"
else
  note "tool attribution found in: $(tr '\n' ' ' <<<"$attribution")"
fi

# ── 9. memory bank freshness ──────────────────────────────────────────

for file in memory-bank/activeContext.md memory-bank/progress.md; do
  if grep -qE '^\*\*Last updated:\*\* [0-9]{4}-[0-9]{2}-[0-9]{2}' "$file"; then
    pass "$file carries a Last updated date"
  else
    note "$file must start with '**Last updated:** YYYY-MM-DD'"
  fi
done

# ── report ────────────────────────────────────────────────────────────

echo
if [[ ${#FAILURES[@]} -eq 0 ]]; then
  ok "documentation rules satisfied"
  exit 0
fi

fail "${#FAILURES[@]} documentation rule(s) violated:"
for failure in "${FAILURES[@]}"; do
  printf '      - %s\n' "$failure"
done
dim "      rules: docs/code-standards.md §5"
exit 1
