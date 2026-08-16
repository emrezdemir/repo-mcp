#!/usr/bin/env bash
#
# Choose which components the Docker stack runs, and write deploy/.env.
#
# Four services are optional: Keycloak, LiteLLM, Ollama and headroom. They are
# Compose profiles rather than separate compose files, because separate files
# would duplicate the four services that are not optional and then drift apart.
# The chosen profiles are written to COMPOSE_PROFILES in deploy/.env, which
# Compose reads on its own — so `make up` needs no extra flags afterwards.
#
# This script is the only thing that writes deploy/.env. scripts/setup.sh calls
# it, so there is one generator rather than two that disagree.
#
# Usage:
#   scripts/wizard.sh                  ask, then write
#   scripts/wizard.sh --defaults       no questions: the full bundled stack
#   scripts/wizard.sh --force          overwrite an existing deploy/.env
#   scripts/wizard.sh --show           print the current choice and exit
#
# Non-interactive selection, for scripted installs:
#   --identity keycloak|external|dev
#   --models   bundled|external|none
#   --compression on|off
#   --database bundled|external
#   --provider github|gitlab|bitbucket|none
#
# Any option given on the command line is not asked about.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_FILE="$REPO_ROOT/deploy/.env"

IDENTITY=""
MODELS=""
COMPRESSION=""
DATABASE=""
PROVIDER=""
ASK=1
FORCE=0
SHOW_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --defaults)    ASK=0 ;;
    --force)       FORCE=1 ;;
    --show)        SHOW_ONLY=1 ;;
    --identity)    IDENTITY="$2"; shift ;;
    --models)      MODELS="$2"; shift ;;
    --compression) COMPRESSION="$2"; shift ;;
    --database)    DATABASE="$2"; shift ;;
    --provider)    PROVIDER="$2"; shift ;;
    -h|--help)     sed -n '2,28p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)             die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

if (( SHOW_ONLY )); then
  # Defined below, so this cannot run inside the parsing loop above.
  ASK=0
fi

# A terminal is required to ask anything. Without one — a pipeline, a
# Dockerfile, a CI step — fall back to the defaults rather than hanging on a
# prompt nobody can answer.
[[ -t 0 ]] || ASK=0

# ── helpers ───────────────────────────────────────────────────────────

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 -c 'import secrets; print(secrets.token_hex(24))'
  fi
}

gen_fernet_key() {
  # Fernet needs a url-safe base64 32-byte key, not an arbitrary hex string.
  "$(py_for common)" -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' \
    2>/dev/null || python3 -c \
    'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
}

#: ask "question" "a|b|c" "default" "explanation for a" "explanation for b" ...
ask_choice() {
  local question="$1" options="$2" default="$3"
  shift 3
  local -a choices
  IFS='|' read -r -a choices <<<"$options"

  printf '\n%b%s%b\n' "$C_BLUE" "$question" "$C_RESET" >&2
  local i=1
  for choice in "${choices[@]}"; do
    local marker=" "
    [[ "$choice" == "$default" ]] && marker="*"
    printf '  %s%d) %-9s %b%s%b\n' "$marker" "$i" "$choice" "$C_DIM" "${1:-}" "$C_RESET" >&2
    shift || true
    i=$((i + 1))
  done

  local answer
  read -r -p "  [${default}] " answer >&2 || answer=""
  [[ -z "$answer" ]] && { echo "$default"; return; }
  # Accept either the number or the name.
  if [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= ${#choices[@]} )); then
    echo "${choices[$((answer - 1))]}"
    return
  fi
  for choice in "${choices[@]}"; do
    [[ "$answer" == "$choice" ]] && { echo "$choice"; return; }
  done
  warn "unrecognised answer '$answer', using $default"
  echo "$default"
}

ask_value() {
  local question="$1" default="${2:-}" answer
  printf '\n%b%s%b\n' "$C_BLUE" "$question" "$C_RESET" >&2
  read -r -p "  ${default:+[$default] }" answer >&2 || answer=""
  echo "${answer:-$default}"
}

show_choice() {
  [[ -f "$ENV_FILE" ]] || { fail "no deploy/.env yet — run scripts/wizard.sh"; return 1; }
  local profiles
  # An .env written before profiles existed has no such line, and grep
  # returning 1 under `set -e` would abort the function silently.
  profiles="$(grep -m1 '^COMPOSE_PROFILES=' "$ENV_FILE" | cut -d= -f2- || true)"
  ok "deploy/.env exists"
  dim "      profiles: ${profiles:-none (core stack only)}"
  dim "      services: postgres, init, gateway, indexer${profiles:+, ${profiles//,/, }}"
  return 0
}

if (( SHOW_ONLY )); then
  show_choice
  exit $?
fi

# ── the questions ─────────────────────────────────────────────────────

if (( ASK )); then
  cat >&2 <<EOF

${C_BLUE}repo-mcp setup${C_RESET}

These choose which containers your stack runs. Everything else — squads,
connectors, tokens, and the identity and model settings — is configured in the
web interface after 'make up'. Press Enter to take the default in brackets;
answers can be changed later by editing deploy/.env or re-running with --force.
EOF
fi

if [[ -z "$DATABASE" ]]; then
  if (( ASK )); then
    DATABASE="$(ask_choice "PostgreSQL" "bundled|external" "bundled" \
      "run one in the stack" \
      "use an instance you already operate")"
  else
    DATABASE=bundled
  fi
fi

if [[ -z "$IDENTITY" ]]; then
  if (( ASK )); then
    IDENTITY="$(ask_choice "Identity" "keycloak|external|dev" "keycloak" \
      "run Keycloak in the stack, federated from LDAP" \
      "use your own OIDC provider (set oidc.issuer afterwards)" \
      "no authentication, static token — evaluation only")"
  else
    IDENTITY=keycloak
  fi
fi

if [[ -z "$MODELS" ]]; then
  if (( ASK )); then
    MODELS="$(ask_choice "Model backend" "bundled|external|none" "bundled" \
      "run LiteLLM and Ollama in the stack" \
      "use your own LiteLLM proxy" \
      "no LLM: the two composite tools stay disabled")"
  else
    MODELS=bundled
  fi
fi

if [[ -z "$COMPRESSION" ]]; then
  if (( ASK )) && [[ "$MODELS" != none ]]; then
    COMPRESSION="$(ask_choice "Prompt compression (headroom)" "off|on" "off" \
      "do not run it" \
      "run it in front of LiteLLM; enable per-setting afterwards")"
  else
    COMPRESSION=off
  fi
fi

# The repository provider is not asked here any more: a connector — its
# provider, organisation and token — is created in the web interface after
# 'make up', where the token is stored encrypted rather than left in a file.
# --provider still works for a scripted install that prefers a token in
# deploy/.env; interactively, all three token variables are written empty as an
# optional fallback and the choice is made in the interface.
PROVIDER="${PROVIDER:-none}"

case "$DATABASE"    in bundled|external) ;;                *) die "--database: bundled or external" ;; esac
case "$IDENTITY"    in keycloak|external|dev) ;;           *) die "--identity: keycloak, external or dev" ;; esac
case "$MODELS"      in bundled|external|none) ;;           *) die "--models: bundled, external or none" ;; esac
case "$COMPRESSION" in on|off) ;;                          *) die "--compression: on or off" ;; esac
case "$PROVIDER"    in github|gitlab|bitbucket|none) ;;    *) die "--provider: github, gitlab, bitbucket or none" ;; esac

[[ "$COMPRESSION" == "on" && "$MODELS" == "none" ]] && \
  die "compression needs a model backend: it sits in front of LiteLLM"

# ── the resulting profile set ─────────────────────────────────────────

PROFILES=()
[[ "$IDENTITY" == keycloak ]] && PROFILES+=(keycloak)
[[ "$MODELS" == bundled ]] && PROFILES+=(litellm ollama)
[[ "$COMPRESSION" == on ]] && PROFILES+=(headroom)
# An answer set with no optional component at all — an external identity
# provider and no model backend — leaves this empty, which is a valid choice:
# the core stack is postgres, init, gateway and indexer. Guarded because macOS
# ships bash 3.2, where expanding an empty array under `set -u` is a fatal
# "unbound variable" instead of the empty string. bash 4.4 fixed it, so no
# Linux host shows this.
PROFILE_LIST=""
if (( ${#PROFILES[@]} )); then
  PROFILE_LIST="$(IFS=,; echo "${PROFILES[*]}")"
fi

DATABASE_URL_LINE="# DATABASE_URL is unset: the bundled PostgreSQL is used."
if [[ "$DATABASE" == external ]]; then
  EXTERNAL_URL=""
  (( ASK )) && EXTERNAL_URL="$(ask_value \
    "PostgreSQL URL (can be filled in later)" \
    "postgresql+asyncpg://repomcp:password@db.internal:5432/repomcp")"
  DATABASE_URL_LINE="DATABASE_URL=${EXTERNAL_URL:-postgresql+asyncpg://repomcp:CHANGEME@db.internal:5432/repomcp}"
fi

# ── write it ──────────────────────────────────────────────────────────

if [[ -f "$ENV_FILE" ]] && (( ! FORCE )); then
  dim "      deploy/.env already exists, left untouched (--force to replace)"
  show_choice
  exit 0
fi

{
  cat <<EOF
# Written by scripts/wizard.sh. Never commit this file.
#
# Chosen components:
#   database    ${DATABASE}
#   identity    ${IDENTITY}
#   models      ${MODELS}
#   compression ${COMPRESSION}
#   provider    ${PROVIDER}
#
# Compose reads COMPOSE_PROFILES from this file, so 'make up' starts exactly
# these services. Change the line and run 'make up' again to add or drop one.
COMPOSE_PROFILES=${PROFILE_LIST}

# --- database ---
POSTGRES_USER=repomcp
POSTGRES_PASSWORD=$(gen_secret)
POSTGRES_DB=repomcp
POSTGRES_PORT=5432
${DATABASE_URL_LINE}

# Encrypts provider tokens at rest. Must stay stable: losing it means
# re-entering every credential.
SECRETS_KEY=$(gen_fernet_key)

# The first administrator. Left empty, it is created in the browser on first
# open (http://localhost:8080/ui). Set a password here to create it at 'make up'
# instead — for CI or an unattended deployment.
ADMIN_USERNAME=admin
ADMIN_PASSWORD=

CONFIG_POLL_SECONDS=15
ENVIRONMENT=local

# --- generated secrets ---
# The last two are only read when their profile is on, but they are always
# written: Compose interpolates every service definition regardless of
# profile, so a missing one would break the whole file.
CI_TRIGGER_TOKEN=$(gen_secret)
KEYCLOAK_ADMIN_PASSWORD=$(gen_secret)
LITELLM_MASTER_KEY=$(gen_secret)
WEBHOOK_SECRET_GITHUB=$(gen_secret)
WEBHOOK_SECRET_GITLAB=$(gen_secret)
WEBHOOK_SECRET_BITBUCKET=$(gen_secret)
EOF

  case "$IDENTITY" in
    keycloak)
      cat <<EOF

# --- identity: bundled Keycloak on :8081 ---
# After the stack is up, create a realm and point the platform at it:
#   repo-mcp-admin set oidc.issuer '"http://keycloak:8080/realms/repo-mcp"'
# Sign in to Keycloak at :8081 as admin, with KEYCLOAK_ADMIN_PASSWORD above.
DEV_INSECURE_AUTH=false
EOF
      ;;
    external)
      cat <<EOF

# --- identity: your own OIDC provider ---
# Nothing to set here; point the platform at it once the stack is up:
#   repo-mcp-admin set oidc.issuer '"https://sso.example.com/realms/main"'
#   repo-mcp-admin set oidc.audience '"repo-mcp"'
DEV_INSECURE_AUTH=false
EOF
      ;;
    dev)
      cat <<EOF

# --- identity: DISABLED ---
# JWT verification is off and this token is accepted as any of the groups
# below. For evaluation on a machine nobody else can reach. The gateway logs a
# warning on every start while this is true.
DEV_INSECURE_AUTH=true
DEV_STATIC_TOKEN=$(gen_secret)
DEV_STATIC_GROUPS=platform-admins
EOF
      ;;
  esac

  case "$MODELS" in
    bundled)
      cat <<EOF

# --- models: bundled LiteLLM (:4000) and Ollama (:11434) ---
# Point the platform at the proxy once the stack is up:
#   repo-mcp-admin set litellm.base_url '"http://litellm:4000/v1"'
#   repo-mcp-admin set litellm.model '"ollama/qwen2.5-coder:14b"'
# Pull the model first:  docker compose exec ollama ollama pull qwen2.5-coder:14b
OLLAMA_BASE_URL=http://ollama:11434
OPENAI_API_KEY=
VLLM_BASE_URL=
VLLM_API_KEY=
EOF
      ;;
    external)
      cat <<EOF

# --- models: your own LiteLLM proxy ---
# Nothing to set here; point the platform at it once the stack is up:
#   repo-mcp-admin set litellm.base_url '"https://litellm.internal/v1"'
# The key is stored encrypted, not in this file:
#   repo-mcp-admin  (see docs/deployment.md for the secret and setting names)
EOF
      ;;
    none)
      cat <<EOF

# --- models: none ---
# explain_change_impact and ask_codebase stay unavailable. The engine's own
# tools are unaffected. To add a proxy later, set litellm.base_url and
# smart_tools.enabled through the admin API.
EOF
      ;;
  esac

  if [[ "$COMPRESSION" == on ]]; then
    cat <<EOF

# --- prompt compression: headroom in front of LiteLLM ---
# Deployed but not used until it is turned on:
#   repo-mcp-admin set headroom.base_url '"http://headroom:8787/v1"'
#   repo-mcp-admin set headroom.enabled true
HEADROOM_VERSION=latest
HEADROOM_UPSTREAM_URL=http://litellm:4000/v1
HEADROOM_OUTPUT_SHAPER=1
EOF
  fi

  echo
  echo "# --- provider tokens for repository discovery ---"
  echo "# Read-only scopes are enough: the indexer clones and lists, never writes."
  case "$PROVIDER" in
    github)    echo "GITHUB_TOKEN=" ;;
    gitlab)    echo "GITLAB_TOKEN=" ;;
    bitbucket) echo "BITBUCKET_APP_PASSWORD=" ;;
    none)      echo "GITHUB_TOKEN="; echo "GITLAB_TOKEN="; echo "BITBUCKET_APP_PASSWORD=" ;;
  esac

  cat <<EOF

# --- engine ---
# Pin this in production: every engine process sharing a cache root must be the
# same build, or they fail with a version cohort conflict.
CBM_VERSION=latest

# --- resource limits ---
GATEWAY_MEMORY_LIMIT=4g
INDEXER_MEMORY_LIMIT=8g
OLLAMA_MEMORY_LIMIT=16g
EOF
} > "$ENV_FILE"

chmod 600 "$ENV_FILE"
ok "wrote deploy/.env"

# ── what happens next ─────────────────────────────────────────────────

cat >&2 <<EOF

${C_BLUE}Stack${C_RESET}
  always      postgres, init, gateway, indexer
  profiles    ${PROFILE_LIST:-none}

${C_BLUE}Next${C_RESET}
EOF

step=1
if [[ "$PROVIDER" != none ]]; then
  case "$PROVIDER" in
    github)    var=GITHUB_TOKEN ;;
    gitlab)    var=GITLAB_TOKEN ;;
    bitbucket) var=BITBUCKET_APP_PASSWORD ;;
  esac
  printf '  %d. Put a token in %b%s%b in deploy/.env\n' "$step" "$C_BLUE" "$var" "$C_RESET" >&2
  step=$((step + 1))
  printf '  %d. Point a connector at your %s org in %bdeploy/scan.yaml%b\n' \
    "$step" "$PROVIDER" "$C_BLUE" "$C_RESET" >&2
  step=$((step + 1))
fi
if [[ "$DATABASE" == external ]]; then
  printf '  %d. Check %bDATABASE_URL%b in deploy/.env\n' "$step" "$C_BLUE" "$C_RESET" >&2
  step=$((step + 1))
fi
printf '  %d. %bmake up%b        start the stack\n' "$step" "$C_BLUE" "$C_RESET" >&2
printf '  %d. %bmake smoke%b     check it end to end\n' "$((step + 1))" "$C_BLUE" "$C_RESET" >&2
printf '\n  %sThen open the interface, create the administrator, and add a connector.%s\n' \
  "$C_DIM" "$C_RESET" >&2
[[ "$IDENTITY" == dev ]] && \
  warn "authentication is disabled — do not expose this beyond your own machine"
echo >&2
