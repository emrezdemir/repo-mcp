<div align="center">

# repo-mcp

### Every repository you own, as one code graph.

repo-mcp indexes your GitHub, GitLab and Bitbucket repositories centrally and
exposes the resulting code graph over **MCP** to coding agents, chatbots and
CI. It is self-hosted and enforces squad-level isolation.

[![License](https://img.shields.io/badge/license-MIT-1da27e.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.4.8-1c8585.svg)](CHANGELOG.md)
[![CI](https://img.shields.io/github/actions/workflow/status/emrezdemir/repo-mcp/ci.yml?branch=dev&label=CI&color=1da27e)](https://github.com/emrezdemir/repo-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-1c8585.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-JSON--RPC-1da27e.svg)](https://modelcontextprotocol.io/)
[![Self-hosted](https://img.shields.io/badge/self--hosted-yes-1c8585.svg)](#install-in-five-minutes)
[![Stars](https://img.shields.io/github/stars/emrezdemir/repo-mcp?style=social)](https://github.com/emrezdemir/repo-mcp)

**[Site](https://emrezdemir.github.io/repo-mcp/en.html)** ·
**[Docs](https://emrezdemir.github.io/repo-mcp/docs/)** ·
[Install](#install-in-five-minutes) ·
[Türkçe](README.md) (primary) ·
[Changelog](CHANGELOG.md)

</div>

<img src="docs/images/ui-graph.png" alt="A 3D view of a code graph with 854 nodes and 4,454 edges">

---

## What it is

Most code intelligence tooling is built for a single developer: everyone indexes
the same repository locally, the resulting graph is rarely shared, and reaching
it from CI or a chatbot is not straightforward. repo-mcp aims to centralise that
for a team.

You define a GitHub organisation, GitLab group or Bitbucket workspace as a
**connector**; the repositories in scope are discovered, cloned and indexed
centrally. Access to the resulting graph goes over **MCP** — JSON-RPC on HTTP.
Each request is authenticated with an **OIDC** token, and the caller's **LDAP**
groups are mapped to a role and a squad.

## Why repo-mcp

- **Index once, everyone uses it.** The same repository is not reindexed on
  everyone's machine. Repositories in a connector's scope are indexed centrally,
  and ones added later join on the next scan.
- **Squad-level isolation.** A squad sees its own code in full detail and other
  squads' services only as topology. This is guaranteed by **three independent
  authorization layers**, not one ACL: role capabilities ∩ project allowlist ∩
  engine tool profile, plus a filesystem root per squad.
- **Answers from the graph, not from guesses.** `ask_codebase` runs the
  deterministic graph query first and lets the model interpret only the evidence
  it returns, citing the symbols it names.
- **No restart.** Squads, roles, connectors and encrypted tokens live in
  PostgreSQL. Every change bumps a generation counter; the services watch it and
  update themselves.
- **Two administrative surfaces, not one.** The `repo-mcp-admin` terminal and
  the web console call the same functions, pass the same validation and produce
  the same audit entry. A test fails if the two ever diverge.

## Install in five minutes

One command is enough to try it. Nothing but Python 3.11+ is required — it
installs the dependencies, the configuration, the indexing engine and the
interface itself:

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp && ./repo-mcp start
```

It prints the address and the sign-in token when it is up; open
`http://localhost:8080/ui`. Stop it with `./repo-mcp stop`, and if something is
wrong, `./repo-mcp doctor` reports every finding rather than the first.

That runs the services directly on your machine — for trying it and developing
against it. A **deployment** is the container stack, which needs Docker Engine
24+ and Compose v2 (or Podman) and is described in
[deployment](https://emrezdemir.github.io/repo-mcp/docs/deployment/).

```bash
make setup     # four questions -> deploy/.env
make up        # schema and services; create the admin in /ui
```

Then define a connector — from the terminal or from the console at
`http://localhost:8080/ui`; both call the same function:

```bash
repo-mcp-admin secret set connector.acme-github.token
repo-mcp-admin connector set acme-github \
  --provider github --squad payments --setting org=acme \
  --token-secret connector.acme-github.token

repo-mcp-admin connector check acme-github
# acme-github: ok — 34 of 41 repositories would be indexed
```

`check` asks the provider what the connector can actually see, and names what
is wrong when something is. For development without Docker, `make dev`.

## Connecting

Every question about the code goes to `POST /mcp` with the caller's own token:

```bash
curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $OIDC_TOKEN" \
  -H "X-Tenant: payments" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

What `tools/list` returns depends on the caller: a tool the role has no
capability for, or that is outside the squad's tool profile, is not in it.

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

## Documentation

All of it is on the site — the architecture, the deployment, the roles, the
scaling and the reasoning behind each decision:
**[emrezdemir.github.io/repo-mcp/docs](https://emrezdemir.github.io/repo-mcp/docs/)**

| Document | Contents |
| --- | --- |
| [Architecture](https://emrezdemir.github.io/repo-mcp/docs/architecture/) | Two services, one engine, a shared graph directory |
| [Web interface](https://emrezdemir.github.io/repo-mcp/docs/web-interface/) | How it is built, how sign-in works, what it does not do |
| [Administration](https://emrezdemir.github.io/repo-mcp/docs/administration/) | The terminal and the console, side by side |
| [Roles and permissions](https://emrezdemir.github.io/repo-mcp/docs/roles-and-permissions/) | What a role may do, what a squad may reach |
| [Deployment](https://emrezdemir.github.io/repo-mcp/docs/deployment/) | Compose, Kubernetes, Keycloak and LDAP |
| [Scaling](https://emrezdemir.github.io/repo-mcp/docs/scaling/) | Replicas, the queue and storage |
| [Decisions (ADR)](https://emrezdemir.github.io/repo-mcp/docs/adr/0001-wrap-dont-fork/) | Why not a fork, why a database, why this interface |
| [Development](https://emrezdemir.github.io/repo-mcp/docs/development/) | Local setup, the tests, the contribution flow |

The source is the markdown under [`docs/`](docs/); the site is rendered from it,
so there is no second copy to drift. The reference docs are English; the landing
pages (site and README) are Turkish.

## Contributing and security

The contribution flow is in [CONTRIBUTING.md](CONTRIBUTING.md) and reporting a
vulnerability is in [SECURITY.md](SECURITY.md). Branch names begin with
`feature/`, `bugfix/`, `hotfix/`, `chore/` or `docs/`; `make verify` is the gate
before a merge.

## Licence

MIT — [LICENSE](LICENSE). The indexing engine is
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT),
wrapped rather than forked; the details are in [NOTICE](NOTICE).
