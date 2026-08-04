#!/usr/bin/env bash
#
# Manage the Docker stack.
#
# Usage:
#   scripts/stack.sh up          build and start everything, wait until healthy
#   scripts/stack.sh up --pull   pull the published images instead of building
#   scripts/stack.sh down        stop, keeping volumes
#   scripts/stack.sh reset       stop and delete volumes (destroys indexes)
#   scripts/stack.sh logs [svc]  follow logs
#   scripts/stack.sh ps          service status
#   scripts/stack.sh restart svc restart one service
#   scripts/stack.sh shell svc   open a shell in a running container
#   scripts/stack.sh scale svc=N scale a service

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_container_engine || exit 1

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
  up)
    [[ -f "$REPO_ROOT/deploy/.env" ]] || die "deploy/.env is missing — run scripts/setup.sh"
    [[ -f "$REPO_ROOT/deploy/tenants.yaml" ]] || die "deploy/tenants.yaml is missing — run scripts/setup.sh"
    [[ -f "$REPO_ROOT/deploy/scan.yaml" ]] || die "deploy/scan.yaml is missing — run scripts/setup.sh"

    # --pull fetches the published images instead of building from source — the
    # path for a server without the disk or the toolchain to build. Everything
    # else after `up` is passed through (service names, extra flags).
    pull=0
    passthrough=()
    for arg in "$@"; do
      case "$arg" in
        --pull) pull=1 ;;
        *) passthrough+=("$arg") ;;
      esac
    done

    if (( pull )); then
      log "pulling published images and starting"
      compose pull "${passthrough[@]}" \
        || die "pull failed — check REPO_MCP_TAG, and log in if the images are private: podman login ghcr.io"
      # --no-build is explicit: some podman-compose versions build a service that
      # has a build: section even on a plain `up`, which would defeat --pull.
      compose up -d --no-build "${passthrough[@]}"
    else
      log "building and starting"
      compose up -d --build "${passthrough[@]}"
    fi

    wait_for_http "http://127.0.0.1:8080/healthz" 120 "gateway" || true
    wait_for_http "http://127.0.0.1:8082/healthz" 120 "indexer" || true
    wait_for_http "http://127.0.0.1:4000/health/liveliness" 90 "litellm" || \
      warn "litellm did not report healthy; smart tools may not work yet"

    echo
    compose ps
    cat <<EOF

  gateway   http://127.0.0.1:8080/mcp
  indexer   http://127.0.0.1:8082
  keycloak  http://127.0.0.1:8081
  litellm   http://127.0.0.1:4000

  ${C_DIM}scripts/debug.sh --docker${C_RESET}   verify the setup
  ${C_DIM}scripts/smoke.sh${C_RESET}            end-to-end check against a real repository
EOF
    ;;

  down)
    log "stopping (volumes kept)"
    compose down "$@"
    ok "stopped"
    ;;

  reset)
    warn "this deletes all indexed data"
    read -r -p "Type 'yes' to continue: " confirm
    [[ "$confirm" == "yes" ]] || die "aborted"
    compose down -v "$@"
    ok "stack and volumes removed"
    ;;

  logs)    compose logs -f --tail=200 "$@" ;;
  ps)      compose ps "$@" ;;
  restart) [[ $# -gt 0 ]] || die "which service?"; compose restart "$@"; ok "restarted $*" ;;
  shell)
    [[ $# -gt 0 ]] || die "which service?"
    compose exec "$1" sh -c 'command -v bash >/dev/null && exec bash || exec sh'
    ;;
  scale)
    [[ $# -gt 0 ]] || die "usage: scripts/stack.sh scale gateway=3"
    compose up -d --scale "$@"
    compose ps
    ;;

  -h|--help|"") sed -n '2,14p' "$0" | sed 's/^# \?//' ;;
  *) die "unknown command: $COMMAND (try --help)" ;;
esac
