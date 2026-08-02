# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-02

### Added

- **A web interface**, served by the gateway at `/ui`. Four pages: an overview
  of what the engine computed about a project, symbol search with source, a
  WebGL map of the graph, and the administrative console. It has no read path
  of its own — every question about a codebase goes to `POST /mcp` with the
  caller's own token, so the browser and an MCP client are authorized and
  audited by exactly the same code. A second read API beside the first would
  be a second place for the tenancy rules to be wrong.
- **Graph rendering that survives a real codebase.** Sigma over graphology,
  using WebGL: one draw call class for all nodes and one for all edges. Canvas
  2D and the SVG-based graph libraries stop being usable in the low thousands,
  and a real graph is tens of thousands. The ForceAtlas2 layout runs in a Web
  Worker so the main thread only draws and the graph can be navigated while it
  settles; a content security policy forbidding `worker-src blob:` falls back
  to slicing the same layout between frames. Filtering by node label and edge
  type happens in the render reducers, so it is instant, reversible, and never
  moves the layout.
- **Authorization Code with PKCE in the browser.** The interface signs in
  through the same issuer the gateway already verifies tokens from — a public
  client with no secret, with the gateway outside the flow. `GET /api/auth`
  publishes the issuer and the public client id so the sign-in screen matches
  the deployment rather than a build-time guess; without a browser client
  configured the token box stays, and in development mode the screen says
  plainly that tokens are not verified. Tokens live in `sessionStorage` only,
  and an expiring one is renewed just before the request that would have
  failed.
- **The administrative console covers the whole API.** Squads, roles,
  connectors, secrets, settings, the answer cache, the audit trail and
  administrator accounts are all editable, through the same routes and
  therefore the same validation the terminal gets — a refusal arrives verbatim.
- **`repo-mcp-admin` covers it too.** `squad`, `role`, `connector`, `secret`,
  `settings`, `audit`, `admins` and `answer-cache` commands, calling the same
  functions the API calls. Parity is a test, not a promise: one check fails if
  an API operation ever arrives without a matching command.
- **[docs/web-interface.md](docs/web-interface.md)** and
  **[docs/administration.md](docs/administration.md)**, and screenshots taken
  from the running interface by `scripts/ui-screenshots.py` rather than drawn.

### Changed

- `/admin/config` also returns the role assignments and the connector filters,
  which the editors need in order to show what they are changing.
- Static files under `ui/` are served by resolving the path and checking it
  stays inside the directory, rather than by matching against a list of names
  that had to be edited every time the interface gained a file.
- `scripts/dev.sh` no longer forces `DEV_INSECURE_AUTH=true`, so a real
  identity provider can be pointed at locally.
- `scripts/check-docs.sh` checks links in tracked files rather than walking the
  working tree, which had started reading a repository cloned under `.dev/`
  for testing.

### Fixed

- The `hidden` attribute is honoured by elements that set `display` in a class
  rule. The sign-in pane stayed on screen underneath the application, because
  `.pane { display: grid }` outranks the browser's own `[hidden]` rule.

## [0.1.0] - 2026-08-01

### Added

- **The optional components are now optional in practice.** Keycloak, LiteLLM,
  Ollama and headroom are Compose profiles, so a deployment with its own
  identity provider and its own model proxy runs four containers instead of
  eight. Profiles rather than a second compose file: separate files would
  duplicate the services that are not optional and then drift apart.
- **`scripts/wizard.sh`** — five questions (database, identity, model backend,
  compression, provider) written to `deploy/.env` as a `COMPOSE_PROFILES`
  line, which Compose reads on its own, so `make up` needs no extra flags. It
  is also the only thing that writes `deploy/.env` now; `scripts/setup.sh`
  calls it rather than generating a second version. Without a terminal it asks
  nothing and writes the full bundled stack, and every answer can be given as
  a flag instead. `make wizard` re-runs it, `--show` prints the current
  selection.

- **One authoritative version.** `VERSION` at the repository root, propagated
  to the three Python packages and the Helm chart by `scripts/version.sh`.
  `--check` runs in `make verify` and in the release workflow, and it fails
  when any of them, or either README, or the changelog disagrees — so the
  rule that a release updates the documentation is enforced rather than
  remembered. `--bump patch|minor|major` does the whole set in one step.
- **Screenshots, generated rather than drawn.** `make screenshots` boots a
  development gateway, captures five real sequences — bootstrap, readiness, an
  MCP round trip, both kinds of refusal, and an administrative change moving
  the generation counter — and renders them as SVG terminal cards into
  `docs/images/`. A README that shows invented output drifts from the code
  without anyone noticing; this one cannot.
- **Turkish is the primary README.** `README.md` is Turkish, written as
  Turkish rather than translated from the English, and `README.en.md` carries
  the English. Both are updated together, and `scripts/version.sh --check`
  fails a release where either one still names an older version.

- **Prompt compression, as a plugin.** Headroom runs as its own pinned
  container in front of LiteLLM, enabled by `headroom.enabled` and disabled by
  the same setting. Nothing is vendored: updating it is bumping an image tag,
  and the chart refuses to deploy it unpinned. An unreachable proxy falls back
  to LiteLLM rather than failing a tool call, embeddings never pass through it
  — compressing the text would move the vector the answer cache keys on — and
  raw engine output cannot reach it at all, because tool results never pass
  through a model. [ADR-0010](docs/adr/0010-headroom-plugin.md).

- **Answer cache.** `ask_codebase` answers are cached per squad and keyed on
  the project's index epoch, so a repeated question costs one indexed row read
  instead of thousands of tokens, and a reindex retires every answer computed
  from the previous graph in one step. An exact-question tier runs first and
  needs no embedding; a semantic tier over the same squad, project and epoch
  runs only when an embedding model is configured, above a deliberately high
  similarity threshold. Off by default, cleared from `/admin/answer-cache`,
  and never crossing a squad boundary.
  [ADR-0009](docs/adr/0009-answer-cache.md).
- **No vector database.** The research behind that is in ADR-0009: after
  filtering by squad, project, tool and epoch the candidate set is small
  enough to score in the gateway, so pgvector buys nothing measurable yet and
  Qdrant buys a second stateful service. The ADR names the number at which
  pgvector becomes the right answer, and the metric that reports it.
- **`project_index_state`** — a monotonic epoch per squad and project, written
  by the indexer after every successful index. Also the first durable answer
  to "when was this project last indexed, and at which commit".

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

- Both services started without `SECRETS_KEY` and only failed later, on the
  first credential they had to decrypt — far from the cause. They now refuse to
  become ready, `/readyz` names the missing variable, and `/healthz` still
  answers so an orchestrator reports the reason instead of a bare crash loop.
  `repo-mcp-admin status` deliberately still works without the key and says it
  is missing: diagnosing exactly that deployment is when the command is worth
  running.
- The image shipped the wrong engine build. The glibc one needs GLIBC 2.38 and
  GLIBCXX 3.4.32; Debian bookworm has 2.36, so it downloaded and verified
  happily and then failed on its first run with a version-not-found from the
  dynamic linker. `CBM_VARIANT` now defaults to `-portable`, which is
  statically linked and depends on nothing — and the build says which flag to
  change if the binary ever refuses to run again.
- The image never copied `common/`, so pip went looking for the path-only
  `repo-mcp-common` on PyPI. Both projects are in the build context now and
  install in one command.
- The image build downloaded the engine from a URL that does not exist. The
  release publishes `codebase-memory-mcp-linux-<arch>.tar.gz`, not a bare
  executable, so every image build failed with `curl` exit 22 and no
  explanation. It now fetches and unpacks the archive, and verifies it against
  the release's own `checksums.txt` — which covers every architecture, so
  `CBM_SHA256` is no longer something anyone has to copy by hand.
- Eight shellcheck warnings, including a `cd` whose failure would have run the
  next command against the wrong tree, and a `--keep` flag in `scripts/smoke.sh`
  that set a variable nothing read. `make test` now runs shellcheck too, so
  these fail locally instead of only on a push.
- `deploy/docker-compose.yml` did not parse — `limits: { memory: ${VAR:-16g} }`
  is not valid YAML unquoted, and a duplicate `ENVIRONMENT` key had crept in.
  Nothing read the file, so nothing said so; `make test` now validates it with
  `docker compose config` when Docker is present.
- Migration `0001` created the schema by calling `Base.metadata.create_all`,
  so it built whatever the models happened to contain — including tables added
  by later revisions, which then failed on a table that already existed. It is
  now transcribed explicitly, and a test compares the migrated schema to the
  models in both directions.
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
