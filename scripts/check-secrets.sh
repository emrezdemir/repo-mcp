#!/usr/bin/env bash
#
# Refuse to commit secrets or environment-specific configuration.
#
# Two checks, because .gitignore alone is not enough — a file added with
# `git add -f`, or one that was tracked before it was ignored, stays tracked
# and .gitignore will not save you.
#
#   1. forbidden paths   — files that must never be tracked at all
#   2. secret patterns   — credential shapes in the content being committed
#
# Usage:
#   scripts/check-secrets.sh              check what is staged (pre-commit)
#   scripts/check-secrets.sh --all        check everything currently tracked
#   scripts/check-secrets.sh --install    install it as a git pre-commit hook

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE=staged
for arg in "$@"; do
  case "$arg" in
    --all)     MODE=all ;;
    --install) MODE=install ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

# ── install ───────────────────────────────────────────────────────────

if [[ "$MODE" == "install" ]]; then
  hook_dir="$(git -C "$REPO_ROOT" rev-parse --git-path hooks)"
  mkdir -p "$hook_dir"
  cat > "$hook_dir/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/check-secrets.sh --install
root="$(git rev-parse --show-toplevel)"
"$root/scripts/check-secrets.sh" || exit 1
"$root/scripts/check-docs.sh" --quiet || exit 1
HOOK
  chmod +x "$hook_dir/pre-commit"
  ok "pre-commit hook installed at $hook_dir/pre-commit"
  dim "      bypass once with: git commit --no-verify"
  exit 0
fi

# ── 1. forbidden paths ────────────────────────────────────────────────

# Environment-specific configuration and generated data. These differ between
# branches and between deployments by design, so tracking any of them is what
# makes main and dev conflict on every merge.
FORBIDDEN_PATTERNS=(
  '(^|/)\.env$'
  '(^|/)\.env\.[^/]*$'
  '(^|/)[^/]*\.env$'
  '^deploy/tenants\.yaml$'
  '^deploy/scan\.yaml$'
  '^deploy/keycloak/'
  '\.db$'
  '\.db-wal$'
  '\.db-shm$'
  '\.zst$'
  '(^|/)id_rsa$'
  '(^|/)id_ed25519$'
  '\.pem$'
  '\.p12$'
  '\.pfx$'
  '(^|/)kubeconfig$'
)

# `.env.example` is a tracked reference with no real values.
ALLOWLIST=(
  '^deploy/\.env\.example$'
)

if [[ "$MODE" == "all" ]]; then
  FILES="$(git -C "$REPO_ROOT" ls-files)"
  SUBJECT="tracked"
else
  FILES="$(git -C "$REPO_ROOT" diff --cached --name-only --diff-filter=ACMR)"
  SUBJECT="staged"
fi

VIOLATIONS=()

allowed() {
  local file="$1" pattern
  for pattern in "${ALLOWLIST[@]}"; do
    [[ "$file" =~ $pattern ]] && return 0
  done
  return 1
}

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  allowed "$file" && continue
  for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
    if [[ "$file" =~ $pattern ]]; then
      VIOLATIONS+=("$file — this path must never be committed")
      break
    fi
  done
done <<< "$FILES"

# ── 2. secret patterns ────────────────────────────────────────────────

# Length-anchored so documentation placeholders such as `ghp_...` do not trip
# them. A pattern that cries wolf gets bypassed, and then it protects nothing.
declare -a SECRET_PATTERNS=(
  'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}'
  'glpat-[A-Za-z0-9_-]{20,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
  'AKIA[0-9A-Z]{16}'
  'sk-[A-Za-z0-9]{32,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.'
)

# Assignments that look like a real value rather than a placeholder or a
# reference to an environment variable name.
declare -a ASSIGNMENT_PATTERNS=(
  '(SECRET|TOKEN|PASSWORD|API_KEY|MASTER_KEY|APP_PASSWORD)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_-]{16,}'
)

scan_content() {
  local file="$1" content pattern
  if [[ "$MODE" == "all" ]]; then
    content="$(cat "$REPO_ROOT/$file" 2>/dev/null || true)"
  else
    content="$(git -C "$REPO_ROOT" show ":$file" 2>/dev/null || true)"
  fi
  [[ -z "$content" ]] && return

  for pattern in "${SECRET_PATTERNS[@]}"; do
    if grep -qE -- "$pattern" <<<"$content"; then
      VIOLATIONS+=("$file — looks like a credential ($pattern)")
    fi
  done

  for pattern in "${ASSIGNMENT_PATTERNS[@]}"; do
    # os.environ / token_env style references name a variable, they do not
    # carry its value.
    if grep -E -- "$pattern" <<<"$content" \
       | grep -qvE '(_env|os\.getenv|os\.environ|environ\[|valueFrom|secretKeyRef|\$\{?[A-Z_]+|<[^>]+>|\.\.\.|example|placeholder|CHANGEME)'; then
      VIOLATIONS+=("$file — assignment with an inline value where an env reference is expected")
    fi
  done
}

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  [[ -f "$REPO_ROOT/$file" ]] || continue
  # Binary files have no credentials worth grepping and produce noise.
  case "$file" in
    *.png|*.jpg|*.gif|*.ico|*.pdf|*.zip|*.gz) continue ;;
  esac
  scan_content "$file"
done <<< "$FILES"

# ── report ────────────────────────────────────────────────────────────

if [[ ${#VIOLATIONS[@]} -eq 0 ]]; then
  count="$(grep -c . <<<"$FILES" || true)"
  ok "no secrets found in ${count:-0} $SUBJECT file(s)"
  exit 0
fi

fail "${#VIOLATIONS[@]} problem(s) found in $SUBJECT files:"
for violation in "${VIOLATIONS[@]}"; do
  printf '      - %s\n' "$violation"
done

cat >&2 <<EOF

Nothing was committed.

  If this is a real secret:      remove it and rotate the credential.
  If it is environment config:   keep it out of git — every value comes from
                                 the environment or from an ignored file.
  If it is a false positive:     git commit --no-verify, then please open an
                                 issue so the pattern can be tightened.
EOF
exit 1
