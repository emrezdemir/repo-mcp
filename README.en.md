<div align="center">

# repo-mcp

**Every repository you own, as one graph.**

Indexes GitHub, GitLab and Bitbucket repositories centrally and exposes the
code graph over MCP to coding agents, chatbots and CI.

[**Site**](https://emrezdemir.github.io/repo-mcp/en.html) ·
[Türkçe](README.md) (primary) ·
[Docs](docs/) ·
[Changelog](CHANGELOG.md)

Version 0.3.0 · MIT

</div>

<img src="docs/images/ui-graph.png" alt="A 3D view of a code graph with 854 nodes and 4,454 edges">

---

## What it does

A GitHub organisation, GitLab group or Bitbucket workspace is defined as a
connector; the repositories in scope are discovered, cloned and indexed.
Access to the resulting graph goes over **MCP** — JSON-RPC on HTTP.
Requests are authenticated with an **OIDC** token and mapped to a role and a
squad from **LDAP** group membership.

|  |  |
| --- | --- |
| **Index once** | The same repository is not reindexed on everyone's machine |
| **Squad isolation** | A squad sees its own code in detail and other squads' only as topology |
| **Three independent layers** | Role capabilities ∩ project allowlist ∩ engine tool profile, plus a filesystem root per squad |
| **No restart** | Configuration lives in PostgreSQL; changes reach the services through a generation counter |
| **Answers from the graph** | `ask_codebase` runs the graph query first; the model is never asked to guess |
| **Two administrative surfaces** | The terminal and the web console call the same functions and produce the same audit entry |

## Install in five minutes

Docker Engine 24+ and Compose v2 is all it needs.

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp && make setup     # five questions -> deploy/.env
make up                       # schema, first administrator, services
```

Then define a connector — from the terminal or from the console at
`http://localhost:8080/ui`; both call the same function:

```bash
repo-mcp-admin secret set connector.acme-github.token
repo-mcp-admin connector set acme-github \
  --provider github --squad payments --setting org=acme \
  --token-secret connector.acme-github.token
```

For development without Docker, `make dev`.

## The interface

<table>
<tr>
<td width="50%"><img src="docs/images/ui-ask.png" alt="Asking a question in words"></td>
<td width="50%"><img src="docs/images/ui-projects.png" alt="The indexed projects list"></td>
</tr>
<tr>
<td><b>Ask.</b> The answer rests on graph evidence and cites the symbols it mentions.</td>
<td><b>Projects.</b> Everything this squad has indexed, with its health and its ADR.</td>
</tr>
<tr>
<td><img src="docs/images/ui-admin.png" alt="The administrative console"></td>
<td><img src="docs/images/ui-signin.png" alt="The sign-in screen"></td>
</tr>
<tr>
<td><b>Administer.</b> Squads, roles, connectors, secrets, settings, audit.</td>
<td><b>Sign in.</b> Authorization Code with PKCE; the browser is a public client.</td>
</tr>
</table>

The interface was not written from scratch: the engine project's own interface
(React and Three.js, MIT) was adopted and pointed at this platform. The
reasoning is in [ADR-0011](docs/adr/0011-adopt-the-upstream-interface.md).

## Connecting

```bash
curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $OIDC_TOKEN" \
  -H "X-Tenant: payments" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

What `tools/list` returns depends on the caller: a tool the role has no
capability for, or that is outside the squad's tool profile, is not in it.

## Documentation

How it is used, the scenarios and the screenshots:
**[emrezdemir.github.io/repo-mcp](https://emrezdemir.github.io/repo-mcp/en.html)**

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | Two services, one engine, a shared graph directory |
| [Web interface](docs/web-interface.md) | How it is built, how sign-in works, what it does not do |
| [Administration](docs/administration.md) | The terminal and the console, side by side |
| [Roles and permissions](docs/roles-and-permissions.md) | What a role may do, what a squad may reach |
| [Deployment](docs/deployment.md) | Compose, Kubernetes, Keycloak and LDAP |
| [Environments](docs/environments.md) | Branches produce artifacts, artifacts promote |
| [Scaling](docs/scaling.md) | Replicas, the queue and storage |
| [ADRs](docs/adr/) | Decisions, and the costs accepted with them |
| [Development](docs/development.md) | Local setup, the tests, the contribution flow |

## Contributing and security

The contribution flow is in [CONTRIBUTING.md](CONTRIBUTING.md) and reporting a
vulnerability is in [SECURITY.md](SECURITY.md). Branch names begin with
`feature/`, `bugfix/`, `hotfix/`, `chore/` or `docs/`; `make verify` is the
gate before a merge.

## Licence

MIT — [LICENSE](LICENSE). The indexing engine is
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT),
wrapped rather than forked; the details are in [NOTICE](NOTICE).
