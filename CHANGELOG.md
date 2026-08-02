# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Environments are separated by artifact and database, not by branch.** CI
  publishes `:dev-<sha>` and `:dev-latest` from `dev`; a `v*.*.*` tag
  publishes `:vX.Y.Z`, `:sha-<commit>` and `:latest`, and packages the chart
  alongside them. Production runs a tag that already ran in dev — nothing is
  rebuilt on the way, and a rollback is redeploying the previous tag.
  [ADR-0008](docs/adr/0008-environments-and-promotion.md),
  [docs/environments.md](docs/environments.md).
- **The chart refuses what it cannot support.** `environment: production` with
  a mutable image tag (`latest`, `dev`, `dev-latest`, `main`, `edge`) or with
  `migrations.auto` fails at template time, as does a release with no database
  or no `SECRETS_KEY`. Each of those otherwise renders cleanly and fails much
  later, somewhere less obvious.
- **`MIGRATE_ON_START`** — whether a starting process may apply the schema. It
  defaults to **false**, the safe answer for the environment nobody is
  watching; the Compose stack and `scripts/dev.sh` set it true, because that is
  where a migration problem should surface. `repo-mcp-admin init` now says so
  by name instead of migrating silently.
- **`ENVIRONMENT`** — a free-form label carried by both services and reported
  by `/readyz`, so "which environment answered" has an answer.
- **Per-environment Helm values** — `deploy/helm/values-dev.example.yaml` and
  `values-production.example.yaml`. Real values files stay untracked, for the
  same reason `deploy/.env` is.
- **`make check-chart`** (`scripts/check-chart.sh`) — catches what `helm lint`
  cannot: a template reading a `.Values` path that no longer exists, which
  renders as an empty string rather than an error. It needs neither a cluster
  nor Helm, and it is part of `make verify`.
- **Release workflow** — a version tag is refused unless the commit is on
  `main`, `Chart.yaml` agrees with the tag, and `CHANGELOG.md` has a section
  for the version.
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

- The Helm chart still mounted `tenants.yaml` and `scan.yaml` and passed OIDC
  and LiteLLM settings as environment variables, none of which the services
  read any more, and it supplied no `DATABASE_URL` at all — so a chart install
  could not have started. It now carries the database, the secret key and the
  environment label, and it runs the schema as a hook Job when asked to.
- The chart pointed both deployments at one image, although `gateway` and
  `indexer` are separate images built from one Dockerfile. The repository is
  now a base and the component is a suffix, matching what CI publishes.
- `scripts/dev.sh` and the CI container smoke both started a service with no
  database, which had become a hard startup failure. `dev.sh` now creates and
  seeds a local SQLite database, and CI runs the image against PostgreSQL —
  the same engine production uses.
- `indexer.concurrency`, `indexer.rescan_interval_seconds` and the indexer
  timeouts were administrator-editable settings that nothing read; the indexer
  took those values from the environment instead. It now reads them from the
  configuration store, and re-reads the rescan interval each pass so a change
  lands without a restart.
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
