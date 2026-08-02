# Architecture

repo-mcp turns code intelligence from a single-user local tool into a shared
service: point it at a GitHub organisation, GitLab group or Bitbucket
workspace, and every repository underneath becomes queryable — by coding
agents over MCP, by chatbots, by CI, and from a web interface.

Parsing and graph construction are done by an embedded third-party engine.
Read [engine.md](engine.md) first: several decisions below follow directly
from what that engine does and does not do.

## Design principle

> Wrap the engine; do not fork it.

The engine carries 158 vendored tree-sitter grammars, a hybrid LSP layer for
eleven languages, a compiled-in embedding model and a signed release pipeline.
Forking means owning all of that. Wrapping means adopting new versions by
changing a version number. Everything repo-mcp adds — transport, identity,
tenancy, audit, reasoning — sits cleanly outside it. See
[ADR-0001](adr/0001-wrap-dont-fork.md).

## Components

```
   Agents (Claude Code, Cursor, Copilot)   Chatbots   CI pipelines   Web UI
                       │                       │           │           │
                       └───────────── MCP over HTTP ────────┴───────────┘
                                       Bearer <OIDC JWT>
                                              │
 ┌────────────────────────────────────────────▼──────────────────────────┐
 │  Gateway (gateway/)                                                   │
 │    auth.py     verify JWT against JWKS; LDAP groups arrive as claims  │
 │    roles.py    role → capabilities                                    │
 │    tenants.py  squad → tenant, project allowlist, tool profile        │
 │    mcp.py      MCP surface; three independent authorization layers    │
 │    cbm.py      one engine process per tenant, over stdio                 │
 │    smart_tools.py  LiteLLM-backed composite tools                     │
 │    audit.py    one JSON record per call                               │
 └───────┬───────────────────────────────────────────┬───────────────────┘
         │ stdio (line-delimited JSON-RPC)           │ HTTPS
         ▼                                           ▼
 ┌───────────────────────┐                ┌──────────────────────────────┐
 │ engine processes         │                │ LiteLLM proxy                │
 │  per tenant:          │                │  squad = virtual key         │
 │   CBM_CACHE_DIR       │                │  budgets, rate limits, logs  │
 │   CBM_ALLOWED_ROOT    │                │  hosted, vLLM or Ollama      │
 │   --tool-profile=…    │                └──────────────────────────────┘
 └──────────┬────────────┘
            │ reads
            ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │ Indexer (indexer/)                                                    │
 │   repos.py      connectors, tenant routing, per-repo bindings         │
 │   webhooks.py   verified push events from all three providers         │
 │   worker.py     queue → git sync → `cbm cli index_repository`         │
 │   main.py       scheduled rescans, CI trigger endpoint                │
 └───────────────────────────────────────────────────────────────────────┘
            ▲                    ▲                      ▲
       push webhook        nightly schedule        CI/CD trigger
```

Both services install `common/` (`repo_mcp_common`): the schema and migrations,
the configuration store, secret encryption, the `repo-mcp-admin` command — and
repository discovery, `providers.py`, which is shared rather than the
indexer's own because the gateway checks a connector against the provider
before the indexer ever runs it.

## Identity: LDAP through Keycloak

LiteLLM has no direct LDAP support, and neither should the gateway — writing
another LDAP bind, session, lockout and MFA implementation is not the job.
Keycloak federates the directory and issues OIDC tokens:

```
Active Directory / OpenLDAP
        │  user federation (read-only bind)
        ▼
   Keycloak realm
        │  group mapper: cn=squad-payments,ou=groups → groups: ["squad-payments"]
        ▼
   OIDC access token  ──▶ gateway (JWKS verification)
                      ──▶ LiteLLM (SSO)
                      ──▶ web UI (authorization code flow)
```

The gateway keeps no user table. Removing someone from an LDAP group revokes
their access at the next token refresh. Keycloak's login page is themeable, so
"our own login screen" and "LDAP-backed" are not in conflict.

CI runners authenticate through the client-credentials flow with a service
account whose group membership grants the same scopes.

## Authorization: three independent layers

| Layer | Enforced by | Protects against |
| --- | --- | --- |
| Role capabilities + project allowlist | `gateway/app/mcp.py` | a user calling a tool or touching a project they should not |
| Engine tool profile (`--tool-profile`) | the engine process | a gateway bug widening the tool surface |
| Filesystem (`CBM_CACHE_DIR`, `CBM_ALLOWED_ROOT`) | the OS | a process reaching another squad's data at all |

None of the three depends on the others being correct.

Roles and squads are deliberately orthogonal — a role says *what you may do*,
squad membership says *to which data*. See
[roles-and-permissions.md](roles-and-permissions.md) and
[ADR-0003](adr/0003-rbac-model.md).

## Tenancy: squad-private and organisation-wide layers

Isolation wants separate stores; cross-repository edges only exist within one
store. The resolution is two layers:

| Layer | Contents | Who reads it |
| --- | --- | --- |
| `tenant/<squad>` | that squad's repositories, full graph | the squad, `analysis` profile |
| `org/public` | all services, structural only: projects, packages, routes, resources and `CROSS_*` edges | everyone, `scout` profile, source-reading tools withheld |

Cross-squad questions ("who calls my endpoint?") are answered from the shared
layer, which by construction contains no function bodies. See
[ADR-0002](adr/0002-tenancy-model.md).

## Indexing: four ways in

The engine ships a git-polling watcher. Centrally that becomes N repositories polled
forever, so repo-mcp drives indexing explicitly instead:

1. **Discovery** — connectors enumerate repositories under an org, group or
   workspace, with include/exclude glob patterns. New repositories are picked
   up without configuration changes.
2. **Webhooks** — push events on the default branch queue an incremental
   index, pinned to the commit the event reported.
3. **Schedule** — a periodic full rescan catches anything webhooks missed and
   refreshes discovery.
4. **CI trigger** — `POST /trigger` indexes one repository at one commit, for
   pipelines that want the graph fresh before running impact analysis.

The queue serialises per project (the engine holds an OS-level mutation lock per
project) and coalesces bursts, since consecutive pushes converge on the same
head.

`persistence: true` writes `.codebase-memory/graph.db.zst`, which developer
machines can bootstrap from instead of reindexing locally. The central service
does not replace local use — they share the same artifact.

## Reasoning: LiteLLM above the engine

The engine contains no model and its embeddings cannot be redirected, so the
reasoning layer sits above it. Because every call goes through LiteLLM,
self-hosted backends (Ollama, vLLM, llama.cpp) are a proxy configuration
concern rather than a code change.

| Tool | Flow |
| --- | --- |
| `explain_change_impact` | `detect_changes` → blast radius → prose risk summary for a pull request |
| `ask_codebase` | question → graph evidence → answer with symbol references |

Raw engine tools are proxied unchanged, so an agent that wants
`search_graph` gets it deterministically and at no token cost. The model is
involved only where synthesis is the point, and it is never asked to guess the
graph — evidence is gathered first.

Per-squad virtual keys mean budgets, rate limits and prompt logs are already
separated by squad on the LiteLLM side.

## Data governance

`get_code_snippet` and `search_code` return raw source. Two consequences:

1. Every call is audited with principal, role, squad, project and outcome
   (`gateway/app/audit.py`), one JSON object per line.
2. What reaches the model is logged by LiteLLM. Even with a fully local
   backend this matters for incident review, not just compliance.

Never expose the engine directly: it has no authentication of its own. The gateway is
the only ingress, and `CBM_ALLOWED_ROOT` is the backstop rather than the
control.

## What is not built yet

Being explicit about this matters more than the diagram above:

- **Web UI.** The codebase map and manual search are on the roadmap and are
  the single largest remaining chunk. The upstream 3D visualiser cannot be
  reused — it binds to localhost by construction.
- **Graph history.** The engine stores only the current graph; before/after
  comparison over time needs retained artifacts and a diff service. See
  [ADR-0004](adr/0004-graph-history.md).
- **On-demand branch indexing.** Querying an arbitrary feature branch that the
  central index has never seen needs ephemeral workers and a quota.

See [roadmap.md](roadmap.md).
