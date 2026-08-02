# Technical context

## Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | `StrEnum`, fast async subprocess handling, the team's language |
| Web | FastAPI + uvicorn | Async, small, no ORM or template layer needed |
| Auth | `python-jose` against JWKS | Verify tokens; never issue them |
| HTTP client | `httpx` (async) | One client for providers and LiteLLM |
| Config | YAML + environment | Reviewable files, secrets from the environment |
| Metrics | `prometheus-client` | What an autoscaler reads |
| Lint/format | `ruff` | One tool, fast |
| Tests | `pytest` + `pytest-asyncio` (auto mode) | Async tests without decorator noise |
| Packaging | setuptools, per service | Two independently installable packages |
| Containers | Multi-stage, `python:3.12-slim`, `tini` | Non-root, engine processes reaped |
| Orchestration | Helm chart; Compose for evaluation | |
| Identity | Keycloak with LDAP federation | LDAP → OIDC without writing an LDAP bind |
| Models | LiteLLM proxy | Hosted, vLLM or Ollama is proxy config, not code |

Deliberately absent: no database (the engine's SQLite files are the store), no
message queue yet (in-process, and that is why the indexer is single-replica),
no ORM, no frontend.

## Repository layout

```
gateway/app/     main asgi mcp auth roles tenants cbm llm smart_tools audit config metrics
indexer/app/     main asgi providers repos webhooks worker metrics
deploy/          Dockerfile docker-compose.yml helm/ *.example.yaml litellm-config.yaml
scripts/         setup test dev debug stack smoke e2e check-secrets lib
docs/            architecture engine roles-and-permissions deployment scaling
                 development branching roadmap adr/
memory-bank/     this directory
```

About 3,400 lines of Python, 50 unit tests, 5 ADRs.

## Environment variables

Full reference in [`deploy/.env.example`](../deploy/.env.example). The ones
that bite:

| Variable | Note |
| --- | --- |
| `CBM_CACHE_ROOT` / `CBM_REPO_ROOT` | Must match between gateway and indexer — the admission barrier keys on the canonical cache root |
| `CBM_VERSION` | Pin in production; `latest` will eventually change the build under a running deployment |
| `CBM_IDLE_TIMEOUT_S` | Bounds gateway memory: each active tenant holds a live engine process |
| `DEV_INSECURE_AUTH` | Skips JWT verification. Local only; the gateway logs a warning |
| `WEB_CONCURRENCY` | Keep at 1. Each uvicorn worker would spawn its own engine process per tenant |

## Constraints that shape the code

**The engine speaks stdio only**, line-delimited JSON-RPC, one call at a time.
Hence a per-tenant process with an `asyncio.Lock` serialising calls, and a
64 MiB stream limit because a full architecture dump arrives as one line.

**A timeout leaves the stream ambiguous.** A late reply would be read as the
next call's result, so a timeout tears the process down rather than retrying
on the same stream.

**stderr must be drained** or the pipe fills and the child blocks.

**Engine builds must match** across every process sharing a cache root.

**SQLite WAL needs real POSIX locking.** Local disk or a block volume. Not
NFS.

## Development environment

```bash
make setup      # venvs in gateway/.venv and indexer/.venv, config, pre-commit hook
make dev        # both services on 8080 and 8082, auto-reload, JWT off
```

The engine binary is usually not installed locally. Everything except tool
execution works without it; a tool call returns
`engine binary not found: ...`. `gateway/tests/test_cbm_bridge.py` runs a fake
engine so the bridge is fully tested without it.

## CI

Runs on `main` and `dev` and on pull requests targeting either:

| Job | Checks |
| --- | --- |
| `test` | lint + tests, gateway and indexer, Python 3.11/3.12/3.13 |
| `secrets` | full-history scan; fails if `.env` or real config is tracked |
| `shell` | `bash -n`, ShellCheck, executable bits |
| `config` | the shipped example files still parse |
| `helm` | `helm lint`, renders with defaults and with autoscaling, and asserts the chart *refuses* autoscaling without `ReadWriteMany` |
| `docker` | builds both images, checks the engine runs and the health probe answers |

## Known environment gotchas

- Installing the services into a system Python can collide with a distro
  `cryptography` build. Use the virtualenvs `make setup` creates.
- `helm` and the engine binary are not available in every sandbox; CI covers
  both.
- `pytest-asyncio` runs in `auto` mode — async tests need no decorator.

## Versions worth pinning attention to

`CBM_VERSION` is the one that can break a running deployment silently. Pin it,
set `CBM_SHA256`, and mirror the download with `CBM_RELEASE_BASE` if the
supply chain must stay internal.
