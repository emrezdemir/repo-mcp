# repo-mcp gateway

The MCP surface agents, chatbots and CI pipelines talk to. It authenticates
callers against OIDC, authorizes them by role and squad, and puts the indexing
engine — which speaks stdio only — behind an HTTP endpoint.

Part of [repo-mcp](../README.md); see
[../docs/architecture.md](../docs/architecture.md) for how it fits together
and [../docs/engine.md](../docs/engine.md) for what the engine imposes.

## Layout

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app: `/mcp`, `/healthz`, `/readyz`, `/metrics` |
| `app/mcp.py` | MCP protocol handling and the authorization decisions |
| `app/auth.py` | OIDC/JWT verification; LDAP groups arrive as claims |
| `app/roles.py` | Roles, capabilities, and how they map to tools |
| `app/tenants.py` | Squad-to-tenant mapping, project allowlists, tool profiles |
| `app/cbm.py` | The stdio bridge: one engine process per tenant |
| `app/llm.py` | LiteLLM client |
| `app/smart_tools.py` | Composite tools that pair a graph query with the model |
| `app/audit.py` | One structured record per call |
| `app/metrics.py` | Prometheus instrumentation |

## Running it

```bash
pip install -e '.[dev]'
pytest

# From the repository root, with auto-reload and JWT verification disabled:
../scripts/dev.sh gateway
```

## Configuration

Squads, roles, connectors, secrets and the identity settings live in the
database and are changed through the admin API. The environment carries only
what has to be known before the database can be read — see `app/config.py`.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL`, `SECRETS_KEY` | Where the configuration lives, and the key protecting credentials in it |
| `ENVIRONMENT`, `MIGRATE_ON_START` | Environment label; whether this process may migrate the schema |
| `OIDC_ISSUER`, `OIDC_AUDIENCE` | Token verification, until an administrator sets them in the database |
| `CBM_BINARY`, `CBM_CACHE_ROOT`, `CBM_REPO_ROOT` | Engine location and storage |
| `CBM_IDLE_TIMEOUT_S` | When to reap an idle engine process |
| `LITELLM_BASE_URL`, `LITELLM_MODEL` | Reasoning layer |
| `DEV_INSECURE_AUTH`, `DEV_STATIC_TOKEN` | Local development only |

## Authorization

Three independent layers, none relying on the others being correct:

1. **Here** — role capabilities intersected with the tenant's tool profile,
   plus the project allowlist.
2. **The engine process** — `--tool-profile`, a fail-closed allowlist.
3. **The filesystem** — per-tenant `CBM_CACHE_DIR` and `CBM_ALLOWED_ROOT`.

Details in [../docs/roles-and-permissions.md](../docs/roles-and-permissions.md).
