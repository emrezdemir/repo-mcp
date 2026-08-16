#!/usr/bin/env bash
#
# Create a user in the bundled Keycloak realm and put them in groups.
#
# The realm in deploy/keycloak/ ships the groups, the clients and the token
# mappers, but no users: a repository that carries a working credential is a
# repository whose credential ends up in production. This creates one, with a
# password you give it or a generated one printed once.
#
# Usage:
#   scripts/keycloak-user.sh ada --group squad-payments
#   scripts/keycloak-user.sh ci-bot --group chapter-devops --password "$PW"
#
# Options:
#   --group NAME       realm group to join; repeatable, at least one needed
#   --password VALUE   defaults to a generated one, printed once
#   --email ADDRESS    defaults to <username>@example.invalid
#   --name "First Last"  defaults to the username
#   --url URL          Keycloak base URL (default: http://localhost:8081)
#   --realm NAME       (default: repo-mcp)
#   --admin NAME       bootstrap admin username (default: admin)
#
# The admin password comes from KEYCLOAK_ADMIN_PASSWORD, which deploy/.env
# already holds — scripts/wizard.sh writes it.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

USERNAME=""
MEMBERSHIPS=()
PASSWORD=""
EMAIL=""
FULL_NAME=""
KC_URL="${KEYCLOAK_URL:-http://localhost:8081}"
REALM="repo-mcp"
ADMIN="admin"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --group)    MEMBERSHIPS+=("$2"); shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --email)    EMAIL="$2"; shift 2 ;;
    --name)     FULL_NAME="$2"; shift 2 ;;
    --url)      KC_URL="$2"; shift 2 ;;
    --realm)    REALM="$2"; shift 2 ;;
    --admin)    ADMIN="$2"; shift 2 ;;
    -h|--help)  sed -n '2,25p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
    -*)         die "unknown option: $1 (try --help)" ;;
    *)          [[ -n "$USERNAME" ]] && die "one username at a time"; USERNAME="$1"; shift ;;
  esac
done

[[ -n "$USERNAME" ]] || die "no username given (try --help)"
(( ${#MEMBERSHIPS[@]} )) || die "a user with no group has no role and no squad; pass --group"

need curl || exit 1
need python3 || exit 1

# An explicitly exported value wins over the file: pointing this at another
# Keycloak should not need deploy/.env edited.
ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-}"
if [[ -z "$ADMIN_PASSWORD" && -f "$REPO_ROOT/deploy/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$REPO_ROOT/deploy/.env" && set +a
  ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-}"
fi
[[ -n "$ADMIN_PASSWORD" ]] || die "KEYCLOAK_ADMIN_PASSWORD is not set; it is in deploy/.env"

GENERATED=0
if [[ -z "$PASSWORD" ]]; then
  PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  GENERATED=1
fi

# ── talk to the admin API ─────────────────────────────────────────────

token="$(curl -fsS -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  -d "username=$ADMIN" --data-urlencode "password=$ADMIN_PASSWORD" 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' 2>/dev/null)" \
  || die "cannot authenticate against $KC_URL as $ADMIN"

# Built in a subshell so the exports do not leak, and passed through the
# environment rather than interpolated: a password is not something to splice
# into a string another program will parse.
payload="$(
  export GROUPS_JSON USERNAME EMAIL PASSWORD FULL_NAME
  GROUPS_JSON="$(printf '%s\n' "${MEMBERSHIPS[@]}")"
  EMAIL="${EMAIL:-$USERNAME@example.invalid}"
  python3 - <<'PY'
import json, os

groups = [f"/{g.lstrip('/')}" for g in os.environ["GROUPS_JSON"].split("\n") if g]

# Keycloak's default user profile requires a first and last name, and a user
# without them is bounced to a "complete your profile" screen on first sign-in
# rather than back to the application. A federated realm gets these from the
# directory; here they come from --name, or from the username.
name = os.environ.get("FULL_NAME") or os.environ["USERNAME"]
first, _, last = name.partition(" ")

print(json.dumps({
    "username": os.environ["USERNAME"],
    "email": os.environ["EMAIL"],
    "firstName": first,
    "lastName": last or first,
    "enabled": True,
    "emailVerified": True,
    "groups": groups,
    "credentials": [
        {"type": "password", "value": os.environ["PASSWORD"], "temporary": False}
    ],
}))
PY
)"

status="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  "$KC_URL/admin/realms/$REALM/users" -d "$payload")"

case "$status" in
  201) ok "created $USERNAME in ${MEMBERSHIPS[*]}" ;;
  409) die "a user named $USERNAME already exists in the $REALM realm" ;;
  404) die "no realm named $REALM at $KC_URL — is the import in deploy/keycloak/ mounted?" ;;
  *)   die "Keycloak refused the request (HTTP $status)" ;;
esac

if (( GENERATED )); then
  echo
  echo "  username:  $USERNAME"
  echo "  password:  $PASSWORD"
  echo
  dim "      Shown once. Sign in at http://localhost:8080/ui"
fi
