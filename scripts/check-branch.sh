#!/usr/bin/env bash
#
# Enforce the branch naming convention in docs/branching.md.
#
# The type prefix is not decoration: it says where a branch came from, where
# it goes, and how urgent it is. A branch called "my-stuff" tells a reviewer
# none of that.
#
# Usage:
#   scripts/check-branch.sh              check the current branch
#   scripts/check-branch.sh NAME         check a given name (CI, pull requests)

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "${1:-}" in
  -h|--help) sed -n '2,11p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
esac

BRANCH="${1:-$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")}"

if [[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]]; then
  # Detached head: a rebase, a bisect or a CI checkout. Nothing to enforce.
  ok "detached HEAD, no branch name to check"
  exit 0
fi

# The long-lived branches are exempt by definition.
if [[ "$BRANCH" == "main" || "$BRANCH" == "dev" ]]; then
  ok "$BRANCH is a long-lived branch"
  exit 0
fi

TYPES="feature|bugfix|hotfix|chore|docs"

if [[ ! "$BRANCH" =~ ^(${TYPES})/[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  fail "invalid branch name: $BRANCH"
  cat >&2 <<EOF

  Expected <type>/<short-description>, lowercase kebab-case:

    feature/  new capability or changed behaviour   (from dev,  into dev)
    bugfix/   defect in unreleased code             (from dev,  into dev)
    hotfix/   defect in released code               (from main, into main and dev)
    chore/    tooling, dependencies, refactors      (from dev,  into dev)
    docs/     documentation only                    (from dev,  into dev)

  Examples: feature/config-in-database, bugfix/webhook-signature-utf8

  Rename the current branch with:
    git branch -m <new-name>

EOF
  exit 1
fi

if (( ${#BRANCH} > 60 )); then
  fail "branch name is ${#BRANCH} characters; the limit is 60"
  exit 1
fi

# A branch named after the tool or person that produced it tells a reviewer
# nothing about the change, and dates badly.
if [[ "$BRANCH" =~ (claude|copilot|cursor|codex|gpt|bot)([/-]|$) ]]; then
  fail "branch name refers to a tool or agent: $BRANCH"
  dim "      name the branch after the change, not after what produced it"
  exit 1
fi

# hotfix branches come off main; catching this early avoids a hotfix that
# silently ships unreleased work from dev.
if [[ "$BRANCH" == hotfix/* ]] && git -C "$REPO_ROOT" rev-parse --verify -q main >/dev/null; then
  if ! git -C "$REPO_ROOT" merge-base --is-ancestor main HEAD 2>/dev/null; then
    warn "$BRANCH does not contain main — a hotfix should branch from main"
    dim "      it must also be merged back into both main and dev"
  fi
fi

ok "branch name '$BRANCH' follows the convention"
