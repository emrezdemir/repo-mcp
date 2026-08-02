# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Configuration in PostgreSQL.** Tenants, roles, project allowlists,
  connectors, OIDC and LiteLLM settings, tunables and provider tokens are rows
  in a database instead of YAML files, changed through an administrative API
  while the platform runs. Only what is needed before the database can be read
  — `DATABASE_URL`, `SECRETS_KEY`, engine paths — stays in the environment.
  [ADR-0006](docs/adr/0006-configuration-in-the-database.md).
- **Bundled PostgreSQL, or your own.** The Compose stack ships a database and
  an `init` container that applies migrations and creates the first
  administrator before either service starts. Setting `DATABASE_URL` at a
  managed instance switches to it with no code change.
- **First administrator on first boot.** `repo-mcp-admin init` creates it,
  interactively or from `ADMIN_USERNAME`/`ADMIN_PASSWORD`, generating and
  printing a password once when none is given. The account reaches the admin
  API only — never MCP tools, a graph or source.
  [ADR-0007](docs/adr/0007-break-glass-administrator.md).
- **Administrative API** at `/admin`: login, tenants, roles, connectors,
  secrets, settings, an audit trail, and a password change. Every write bumps
  a generation counter, so a change reaches every replica within one poll
  interval without a restart.
- **Encrypted credentials.** Provider tokens and virtual keys are stored
  Fernet-encrypted, keyed from the environment, so a database dump is not by
  itself a credential disclosure. Values are never returned by the API and
  never written to an audit record.
- **`repo-mcp-admin`** — `init`, `init-db`, `create-admin`, `set-password`,
  `import`, `set`, `status`, `generate-key`. Every command is safe to re-run.
  `import` seeds from the existing YAML and moves token values out of the
  environment into encrypted storage.
- **`common/`** — the shared package holding the schema, migrations, secret
  encryption, the configuration store and the bootstrap flow, with 32 tests
  that run against SQLite and need no database server.
- **Branch naming convention** — `feature/`, `bugfix/`, `hotfix/`, `chore/`,
  `docs/`, enforced by `scripts/check-branch.sh` in the pre-commit hook and in
  CI. A `hotfix/` branches from `main` and merges into both `main` and `dev`.
- **Working agreement for agents** — `AGENTS.md` is the binding contract
  (commands, git workflow, hard rules, code standards, testing, definition of
  done). `CLAUDE.md` is a thin tool-specific layer that defers to it rather
  than repeating it, so the two cannot drift apart.
- **Memory bank** (`memory-bank/`) — durable project context an agent reads at
  session start: project brief, product context, system patterns and
  invariants, technical context, active context and progress. `progress.md`
  uses a strict status vocabulary and separates *works* from *built but
  unverified* from *designed*.
- **`docs/code-standards.md`** — binding code, test, shell, commit and
  documentation rules. Every rule is marked as mechanically enforced or
  reviewed.
- **`scripts/check-docs.sh`** — enforces the documentation rules: required
  files present and non-empty, every internal link resolves, every `make`
  command in `AGENTS.md` exists, every `make` target is documented, changelog
  has an `[Unreleased]` section, ADRs carry the required sections including
  negative consequences and rejected alternatives, the README index resolves,
  no tool attribution is committed, and the memory bank carries a date.
  Wired into `make test`, the pre-commit hook and CI.
- **`make verify`** — the single gate matching the definition of done: tests,
  documentation rules and secret scan.
- **Gateway** — MCP over HTTP in front of the indexing engine: one engine
  process per tenant over stdio, with idle reaping and timeout recovery.
- **Identity** — OIDC/JWT verification against JWKS, with LDAP groups arriving
  as token claims; a development mode with a static token.
- **Authorization** — three independent layers: role capabilities and project
  allowlists in the gateway, the engine's fail-closed tool profile, and
  per-tenant filesystem roots.
- **Roles** — `admin`, `lead`, `developer`, `qa`, `devops`, `viewer`, with
  capabilities and squad scope kept orthogonal so chapter members need no
  special-casing.
- **Audit** — one structured JSON record per call, including denials.
- **Reasoning** — LiteLLM-backed `explain_change_impact` and `ask_codebase`;
  hosted, vLLM and Ollama backends are proxy configuration.
- **Discovery** — connectors for GitHub organisations, GitLab groups
  (including nested subgroups) and Bitbucket workspaces or projects, with
  include/exclude globs.
- **Indexing** — verified webhooks for all three providers, a periodic rescan,
  and a CI trigger endpoint; the queue serialises per project and coalesces
  bursts.
- **Observability** — Prometheus metrics on both services: MCP request and
  tool-call counters, tool and index latency histograms, live engine process
  count and restarts, indexing queue depth, discovery and webhook outcomes.
- **Packaging** — multi-stage images with a pinned, optionally checksummed
  engine build, running non-root under `tini`; a Compose stack with health
  checks and resource limits; a Helm chart with autoscaling, pod disruption
  budgets, ServiceMonitors, network policies and ingress.
- **Scripts** — `setup`, `test`, `dev`, `debug`, `stack`, `smoke` and `e2e`,
  plus a `Makefile` wrapping them.
- **Documentation** — architecture, source-verified engine constraints, roles
  and permissions, deployment, scaling, development, roadmap, and five
  decision records.

### Fixed

- A freshly bootstrapped database crashed the gateway at startup, because an
  empty tenant list was treated as a configuration error. That is the state
  every new deployment is in; an empty registry is now valid and `/readyz`
  reports it rather than looking healthy.
- ADR-0001 and ADR-0003 were missing their *Alternatives considered*
  sections, found by the new documentation check on its first run. An ADR
  without rejected alternatives leaves the next reader unable to tell whether
  the obvious option was considered.

### Notes

- The Helm chart refuses to render a gateway HPA unless the cache volume is
  `ReadWriteMany`. A replica without access to the graph stores answers
  queries from an empty graph, which reads as a code problem rather than a
  deployment one.
- Both workloads use the `Recreate` strategy: the engine's exact-build
  admission barrier fails when old and new pods share a cache root.
- A missing or unstartable engine binary is reported as a JSON-RPC error
  naming the cause, rather than surfacing as an opaque HTTP 500.

[Unreleased]: https://github.com/emrezdemir/repo-mcp/commits/main
