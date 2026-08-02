# repo-mcp

**Centralized code intelligence for the whole organisation.** Point it at a
GitHub organisation, GitLab group or Bitbucket workspace, and every repository
underneath becomes a queryable knowledge graph — for coding agents over MCP,
for chatbots, and for CI pipelines.

[Türkçe](README.tr.md)

---

`repo-mcp` wraps [codebase-memory-mcp][cbm] (CBM), an excellent local code
intelligence engine, and supplies what a shared deployment needs and CBM
deliberately does not have: network transport, LDAP-backed identity,
squad-level tenancy, role-based authorization, audit logging, automatic
repository discovery, and an LLM reasoning layer routed through
[LiteLLM][litellm].

The engine is never modified. Upstream releases are adopted by changing a
version number — see [ADR-0001](docs/adr/0001-wrap-dont-fork.md).

[cbm]: https://github.com/DeusData/codebase-memory-mcp
[litellm]: https://github.com/BerriAI/litellm

## Why

CBM indexes a repository into a knowledge graph so an agent can ask *"who
calls this function?"* instead of grepping. It is fast, offline and
single-user by design: stdio only, no authentication, one cache directory per
account.

That design is right for a laptop and wrong for an organisation. Every
developer reindexes the same repositories, no graph is shared across teams,
and there is no way to answer a cross-service question or to hand the same
knowledge to a chatbot or a CI job.

repo-mcp keeps the engine and adds the missing half.

## What it does

- **Discovers repositories automatically.** One connector per GitHub
  organisation, GitLab group (nested subgroups included) or Bitbucket
  workspace, filtered with glob patterns. New repositories are picked up
  without touching configuration.
- **Keeps the graph fresh, four ways.** Verified push webhooks, a periodic
  rescan, an explicit CI trigger, and manual re-index.
- **Speaks MCP over HTTP.** Any MCP client — Claude Code, Cursor, Copilot, a
  chatbot, a pipeline — connects to one endpoint with an OIDC token.
- **Authenticates against LDAP.** Active Directory or OpenLDAP, federated
  through Keycloak; the gateway keeps no user table of its own.
- **Isolates by squad, with three independent layers.** Role capabilities and
  project allowlists in the gateway, the engine's own fail-closed tool profile,
  and per-tenant filesystem roots. A mistake in one does not open the others.
- **Adds reasoning through LiteLLM.** Change-impact narratives and
  natural-language questions, backed by hosted models, vLLM or Ollama — a proxy
  configuration choice, not a code change.
- **Audits everything.** One structured JSON record per call, including
  denials, because `get_code_snippet` returns real source.

## Architecture at a glance

```
 Agents · Chatbots · CI ──MCP over HTTP + OIDC──▶ Gateway ──stdio──▶ CBM (per tenant)
                                                    │
                                                    └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook/schedule──▶ Indexer ──▶ graph store
```

Full detail in [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp/deploy

cp tenants.example.yaml tenants.yaml     # roles, squads, project allowlists
cp scan.example.yaml scan.yaml           # which orgs/groups to index

export LITELLM_MASTER_KEY=$(openssl rand -hex 24)
export GITHUB_TOKEN=ghp_...              # read-only, for discovery
export CI_TRIGGER_TOKEN=$(openssl rand -hex 24)

docker compose up --build
```

Then discover and index:

```bash
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

Point an MCP client at `http://localhost:8080/mcp` with an OIDC bearer token
and an `X-Tenant` header. The full walkthrough, including Keycloak and LDAP
setup, is in [docs/deployment.md](docs/deployment.md).

## Configuration

Two files, both safe to commit — every secret comes from the environment.

`tenants.yaml` — who may do what, to which data:

```yaml
roles:
  admin:     [platform-admins]
  developer: [squad-payments]
  devops:    [chapter-devops]

tenants:
  payments:
    ldap_groups: [squad-payments, chapter-devops]
    tool_profile: analysis          # read-only engine surface
    projects: ["acme-payments-*", "acme-ledger"]
```

`scan.yaml` — what to index:

```yaml
connectors:
  - name: acme-github
    type: github
    org: acme
    token_env: GITHUB_TOKEN
    tenant: payments
    include: ["payments-*"]
    exclude: ["*-archive"]
    mode: moderate
```

## Documentation

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | components, data flow, what is not built yet |
| [Engine constraints](docs/cbm-constraints.md) | source-verified CBM behaviours that shape the design |
| [Roles and permissions](docs/roles-and-permissions.md) | capabilities, roles, chapters, how the axes combine |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, webhooks, CI, production notes |
| [Roadmap](docs/roadmap.md) | done, next, and explicitly not planned |
| [Decision records](docs/adr/) | why the design is what it is |

## Status

Early. The gateway and the indexer work and are covered by tests; the web UI
and graph history are designed but not built.
[docs/roadmap.md](docs/roadmap.md) is explicit about which is which — please
read it before assuming a feature exists.

## Development

```bash
cd gateway && pip install -e '.[dev]' && pytest
cd ../indexer && pip install -e '.[dev]' && pytest
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT, matching the engine it wraps. See [LICENSE](LICENSE).

`repo-mcp` is an independent project, not affiliated with or endorsed by the
codebase-memory-mcp maintainers.
