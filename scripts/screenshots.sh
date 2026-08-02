#!/usr/bin/env bash
#
# Regenerate the images in docs/images/ from a running platform.
#
# The platform has no web interface, so a "screenshot" here is a terminal
# card: the real request and the real answer, captured from a live gateway
# rather than typed out by hand. That is the point — a README that shows
# invented output is a README that drifts from the code without anyone
# noticing.
#
# Rendered as SVG: crisp at any size, a few kilobytes, no binary blobs in
# review, and readable on light and dark backgrounds alike.
#
# Usage:
#   scripts/screenshots.sh            boot a dev gateway, capture, render
#   scripts/screenshots.sh --render   re-render from the last capture only
#
# Requires the engine binary on PATH; without it the tool listing is empty
# and the images would understate what the platform does.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

RENDER_ONLY=0
case "${1:-}" in
  --render) RENDER_ONLY=1 ;;
  -h|--help) sed -n '2,20p' "$0" | sed 's/^# \?//'; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac

IMAGES="$REPO_ROOT/docs/images"
CAPTURES="$REPO_ROOT/.dev/captures"
mkdir -p "$IMAGES" "$CAPTURES"

# ── capture ───────────────────────────────────────────────────────────

capture() {
  need curl || exit 1

  command -v "${CBM_BINARY:-codebase-memory-mcp}" >/dev/null 2>&1 \
    || die "the engine binary is not on PATH; the captures would understate the platform"

  log "starting a development gateway"
  rm -rf "$REPO_ROOT/.dev/repo-mcp.db"
  "$REPO_ROOT/scripts/dev.sh" gateway > "$CAPTURES/server.log" 2>&1 &
  local dev_pid=$!
  # shellcheck disable=SC2064  # the PID must be captured now, not at trap time
  trap "kill $dev_pid 2>/dev/null; pkill -f 'uvicorn app.asgi' 2>/dev/null; true" EXIT

  wait_for_http "http://127.0.0.1:8080/readyz" 60 "the gateway" || die "the gateway never became ready"

  local gw=http://127.0.0.1:8080

  # 1. Bringing it up: schema, seed data and the first administrator.
  sed -n '1,12p' "$CAPTURES/server.log" > "$CAPTURES/01.txt"

  # 2. What the platform says it is serving.
  curl -sS "$gw/readyz" | python3 -m json.tool > "$CAPTURES/02.txt"

  # 3. An MCP round trip. Names only: the schemas are long and say nothing
  #    a reader of a README needs.
  curl -sS "$gw/mcp" -H 'Authorization: Bearer devtoken' \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    | python3 -c "
import json, sys
tools = json.load(sys.stdin)['result']['tools']
print('{')
print('  \"jsonrpc\": \"2.0\", \"id\": 1,')
print('  \"result\": { \"tools\": [')
for i, tool in enumerate(tools):
    comma = ',' if i < len(tools) - 1 else ''
    print(f'    {{ \"name\": \"{tool[\"name\"]}\" }}{comma}')
print('  ] }')
print('}')
print()
print(f'# {len(tools)} tools, and this squad sees all of them: its profile is')
print('# read-only, so nothing that mutates a graph was offered in the first place.')
" > "$CAPTURES/03.txt"

  # 4. Both refusals, because they fail differently and both matter: a project
  #    outside the squad's allowlist, and a squad the caller is not in.
  {
    curl -sS "$gw/mcp" -H 'Authorization: Bearer devtoken' \
      -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_graph","arguments":{"project":"someone-elses-repo","query":"auth"}}}' \
      | python3 -m json.tool
    echo
    curl -sS -w '\nHTTP %{http_code}' "$gw/mcp" -H 'Authorization: Bearer devtoken' \
      -H 'X-Tenant: checkout' -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":3,"method":"tools/list"}'
    echo
  } > "$CAPTURES/04.txt"

  # 5. An administrative change, and the generation counter that carries it to
  #    every replica without a restart.
  local token
  token="$(curl -sS -X POST "$gw/admin/login" -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"devadmin-password"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
  {
    echo "# before"
    curl -sS "$gw/readyz" | python3 -c 'import json,sys; print("generation:", json.load(sys.stdin)["generation"])'
    echo
    curl -sS -X PUT "$gw/admin/settings/answer_cache.enabled" \
      -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
      -d '{"value": true}'
    echo
    echo
    echo "# after"
    curl -sS "$gw/readyz" | python3 -c 'import json,sys; print("generation:", json.load(sys.stdin)["generation"])'
  } > "$CAPTURES/05.txt"

  ok "captured 5 sequences from a live gateway"
}

# ── render ────────────────────────────────────────────────────────────

render() {
  python3 - "$CAPTURES" "$IMAGES" <<'PY'
import html
import re
import sys
from pathlib import Path

captures, images = Path(sys.argv[1]), Path(sys.argv[2])

# name, title, the command a reader would have typed
CARDS = [
    ("01-bootstrap", "make dev", "$ make dev"),
    ("02-readyz", "readiness", "$ curl -s localhost:8080/readyz | jq"),
    ("03-mcp-tools", "MCP: tools/list",
     "$ curl -s localhost:8080/mcp -H 'Authorization: Bearer $TOKEN' \\\n"
     "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' | jq"),
    ("04-denied", "authorization",
     "$ # a project outside the squad's allowlist, then another squad"),
    ("05-admin", "admin API",
     "$ curl -X PUT localhost:8080/admin/settings/answer_cache.enabled \\\n"
     "    -H \"Authorization: Bearer $ADMIN\" -d '{\"value\": true}'"),
]

ANSI = re.compile(r"\x1b\[[0-9;]*m")

CHAR_W = 8.4       # DejaVu Sans Mono at 14px
LINE_H = 21
PAD_X, PAD_Y = 22, 18
BAR_H = 34

# One dark card, deliberately: it reads as a terminal on a light page and on a
# dark one, where a theme-following card would need CSS GitHub strips anyway.
BG, BAR, FG, DIM, ACCENT, OK, BAD = (
    "#12161c", "#1b212a", "#d5dde8", "#7c8798", "#8ab4f8", "#7ee2a8", "#ff8f8f"
)


def colour(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("$") or stripped.startswith("#"):
        return DIM
    if "error" in stripped.lower() or "no access" in stripped or "HTTP 4" in stripped:
        return BAD
    if stripped.startswith("ok ") or '"status": "ok"' in stripped or stripped.startswith("==>"):
        return OK
    return FG


def card(name: str, title: str, command: str, body: str) -> str:
    lines = [ANSI.sub("", ln).rstrip() for ln in command.split("\n")]
    lines.append("")
    lines += [ANSI.sub("", ln).rstrip() for ln in body.rstrip().split("\n")]

    width = max(len(ln) for ln in lines)
    w = int(PAD_X * 2 + width * CHAR_W)
    h = int(BAR_H + PAD_Y * 2 + len(lines) * LINE_H)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}">',
        f'<rect width="{w}" height="{h}" rx="10" fill="{BG}"/>',
        f'<path d="M0 10a10 10 0 0 1 10-10h{w - 20}a10 10 0 0 1 10 10v{BAR_H - 10}H0z" fill="{BAR}"/>',
    ]
    for i, dot in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'<circle cx="{20 + i * 18}" cy="{BAR_H / 2}" r="6" fill="{dot}"/>')
    out.append(
        f'<text x="{w / 2}" y="{BAR_H / 2 + 4}" fill="{ACCENT}" text-anchor="middle" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12">'
        f"{html.escape(title)}</text>"
    )

    y = BAR_H + PAD_Y + 12
    for line in lines:
        if line:
            out.append(
                f'<text x="{PAD_X}" y="{y}" fill="{colour(line)}" '
                f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
                f'font-size="14" xml:space="preserve">{html.escape(line)}</text>'
            )
        y += LINE_H

    out.append("</svg>")
    return "\n".join(out) + "\n"


written = 0
for name, title, command in CARDS:
    source = captures / f"{name.split('-')[0]}.txt"
    if not source.exists():
        print(f"  missing capture: {source.name}", file=sys.stderr)
        continue
    (images / f"{name}.svg").write_text(card(name, title, command, source.read_text()))
    written += 1

print(f"  rendered {written} image(s) into {images}")
raise SystemExit(0 if written == len(CARDS) else 1)
PY
}

if (( ! RENDER_ONLY )); then
  capture
fi

log "rendering"
render || die "rendering failed — run without --render to capture first"
ok "docs/images is up to date"
