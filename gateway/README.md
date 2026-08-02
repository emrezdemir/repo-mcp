# repo-mcp gateway

The MCP surface agents, chatbots and CI pipelines talk to. It authenticates
callers against OIDC, authorizes them by role and squad, and proxies the
[codebase-memory-mcp][cbm] engine — which speaks stdio only — over HTTP.

Part of [repo-mcp](../README.md); see [../docs/architecture.md](../docs/architecture.md)
for how it fits together.

[cbm]: https://github.com/DeusData/codebase-memory-mcp

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

All from the environment; see `app/config.py` for the full list and defaults.

| Variable | Purpose |
| --- | --- |
| `OIDC_ISSUER`, `OIDC_AUDIENCE` | Token verification |
| `TENANTS_FILE` | Path to `tenants.yaml` |
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
