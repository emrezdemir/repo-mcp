# repo-mcp

**Centralized code intelligence for the whole organisation.** Point it at a
GitHub organisation, GitLab group or Bitbucket workspace, and every repository
underneath becomes a queryable knowledge graph — for coding agents over MCP,
for chatbots, and for CI pipelines.

[Türkçe](README.tr.md)

---

Ask *"who calls this function?"*, *"what breaks if I change this?"* or *"which
services hit this endpoint?"* and get an answer computed from the code itself,
not guessed from a context window.

repo-mcp runs as a service your whole company shares: LDAP-backed login,
squad-level isolation, role-based permissions, automatic repository discovery,
audit logging, and an LLM reasoning layer routed through your own
[LiteLLM](https://github.com/BerriAI/litellm) proxy — hosted models, vLLM or
Ollama, your choice.

## Why

Code intelligence tools are built for one developer on one laptop. That is the
wrong shape for a company: every developer reindexes the same repositories, no
graph is ever shared between teams, cross-service questions cannot be answered
at all, and none of that knowledge is reachable from a chatbot or a CI job.

repo-mcp makes it a shared service — indexed once, centrally, with the access
control an organisation actually needs.

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
  through Keycloak; repo-mcp keeps no user table of its own.
- **Isolates by squad, with three independent layers.** Role capabilities and
  project allowlists at the gateway, a fail-closed tool profile inside the
  engine process, and per-tenant filesystem roots. A mistake in one does not
  open the others.
- **Answers in prose when that helps.** Change-impact summaries for pull
  requests and natural-language questions, always grounded in a graph query
  first — the model is never asked to guess the graph.
- **Audits everything.** One structured JSON record per call, including
  denials, because reading a snippet means reading real source.

## Architecture at a glance

```
 Agents · Chatbots · CI ──MCP over HTTP + OIDC──▶ Gateway ──▶ indexing engine
                                                    │          (per tenant)
                                                    └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook/schedule──▶ Indexer ──▶ graph store
```

Two services. The **gateway** authenticates, authorizes and serves the MCP
surface. The **indexer** discovers repositories and keeps their graphs current.
Both drive an embedded indexing engine; see [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

make setup      # virtualenvs, dependencies, config files, generated secrets
# edit deploy/.env (add a provider token) and deploy/scan.yaml
make up         # build and start the Docker stack
make smoke      # verify it end to end
```

Then discover and index:

```bash
source deploy/.env
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

Point an MCP client at `http://localhost:8080/mcp` with an OIDC bearer token
and an `X-Tenant` header. The full walkthrough, including Keycloak and LDAP
setup, is in [docs/deployment.md](docs/deployment.md).

If something does not work, `make debug` checks the toolchain, the engine, the
configuration, storage, both services, an MCP round trip and the model
backend — and reports everything it finds rather than stopping at the first
problem.

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
| [Roles and permissions](docs/roles-and-permissions.md) | capabilities, roles, chapters, how the axes combine |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, webhooks, CI, production notes |
| [Scaling](docs/scaling.md) | storage topologies, what to watch, capacity planning |
| [Development](docs/development.md) | the scripts, the test layers, how to debug |
| [Indexing engine](docs/engine.md) | what the embedded engine does, and the limits it imposes |
| [Roadmap](docs/roadmap.md) | done, next, and explicitly not planned |
| [Decision records](docs/adr/) | why the design is what it is |

## Status

Early. The gateway and the indexer work and are covered by tests; the web UI
and graph history are designed but not built.
[docs/roadmap.md](docs/roadmap.md) is explicit about which is which — please
read it before assuming a feature exists.

## Development

```bash
make setup      # virtualenvs and dependencies
make test       # lint and unit tests for both services
make dev        # run both services locally, no Docker, auto-reload
make debug      # diagnose whatever is not working
make e2e        # build images, index a real repository, query it, tear down
make help       # everything else
```

Every target is a script in [`scripts/`](scripts/) — run them directly if you
prefer. Details in [docs/development.md](docs/development.md).

Kubernetes deployment uses the Helm chart in
[`deploy/helm/repo-mcp`](deploy/helm/repo-mcp); read
[docs/scaling.md](docs/scaling.md) before raising any replica count, because
the storage topology constrains it.

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

repo-mcp bundles a third-party indexing engine; its licence and attribution
are in [NOTICE](NOTICE).
