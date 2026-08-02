# Active context

**Last updated:** 2026-08-02
**Branch:** `feature/adopt-graph-ui`, off `dev`

## Where things stand

Configuration lives in PostgreSQL, with an administrative API, a first-boot
administrator and encrypted credentials. Both services read it at runtime and
pick up changes without a restart.

Deployment now has a shape: branches produce images, images are promoted to
environments, and configuration is never promoted. CI publishes `:dev-<sha>`
from `dev`; a version tag publishes `:vX.Y.Z` and packages the chart.

`main` is still at the initial commit — the maintainer merges `dev` into it;
nothing else pushes there.

## What the last sessions did

**Session 11 — the interface was rewritten, and it should not have been.**
The maintainer had asked for the upstream project to be used as the base. It
was cloned and read this session rather than assumed about: the engine is
1,229 C files with 43 MB of vendored dependencies, but `graph-ui` is 60 files
of React and Three.js that move independently of it, and upstream's client
already posts JSON-RPC `tools/call` — the same protocol the gateway accepts
at `/mcp`. So the interface written here was deleted and upstream's adopted,
at commit d6be58ef. ADR-0011 records it; ADR-0001 is unchanged.

The 3D layout was the one real obstacle: it is 860 lines of C serving on a
loopback port, not an MCP tool. Rather than reimplement it, the gateway now
starts each tenant's engine with that server on a port of its choosing and
proxies `GET /api/layout` after authorizing exactly as it authorizes a tool
call. Verified against the real engine: 401 without a token, the platform's
own refusal for another squad's project, and the port refusing every address
but loopback.

Everything upstream reached for over HTTP became a tool call, so each is
behind a capability. Two surfaces were removed rather than rewired — the
filesystem browser and the process/log views — because they are meaningful on
one machine and not on a shared platform.

The costs are real and recorded: a Node build stage, a second dependency
ecosystem, an npm mirror needed for an air-gapped build, and the engine build
that includes the interface (`CBM_EDITION=-ui`). Version 0.3.0.

**Session 10 — the web interface, and administrative parity.** The gateway
serves a browser interface at `/ui`: overview, search, a WebGL map of the
graph, and the administrative console. It has no read path of its own —
everything about a codebase goes to `POST /mcp` with the caller's own token —
so there is exactly one place the tenancy rules are enforced.

Signing in is Authorization Code with PKCE against the configured issuer. That
was verified end to end in a real browser against a stand-in provider that
signs RS256 tokens the gateway verifies through its ordinary JWKS path:
redirect out and back, code exchanged, groups claim mapped to role and squad,
code removed from the address bar, refresh before expiry, sign-out clearing
storage. `scripts/dev.sh` no longer forces `DEV_INSECURE_AUTH`, which is what
made that test possible.

Rendering is Sigma over graphology with the ForceAtlas2 layout in a Web
Worker. Four defects were found by actually loading the page rather than by
reading it: the layout module is `layoutForceAtlas2`, not `layout.forceAtlas2`;
`query_graph` returns `labels(x)` as the JSON text `["Class"]` rather than an
array, so every node was grey; `.pane { display: grid }` outranks the
browser's `[hidden]` rule, so the sign-in pane stayed on screen underneath the
application; and a node selected while the layout was still running drifted
off-screen, because Sigma renormalises coordinates as the graph expands.

Parity was the other half. The administrative API could already create squads,
roles, connectors and secrets; neither the CLI nor the interface could. Both
now can, through the same functions, with a test that fails if an API
operation ever arrives without a matching command. Version 0.2.0.

**Session 9 — CI turned red, and it was telling the truth.** The image build
had never worked: it fetched the engine from a URL that does not exist, and
behind that it never copied the shared `common/` package, so pip went looking
for `repo-mcp-common` on PyPI. Eight shellcheck warnings too. All fixed, and
`make test` now runs shellcheck and validates the Compose file, so these fail
locally rather than only on a push.

Also: `VERSION` is now the single authoritative number, `make screenshots`
generates `docs/images/` from a live gateway, and `README.md` is Turkish with
`README.en.md` alongside it. `scripts/version.sh --check` — part of
`make verify` — fails when a package, the chart, either README or the
changelog disagrees, which is what makes "every release updates the
documentation" a rule rather than a hope.

**Session 8 — prompt compression as a plugin.** Headroom runs as its own
pinned container in front of LiteLLM, enabled by a database setting and
removed by the same one. Nothing vendored: updating it is a tag bump, and the
chart refuses an unpinned tag. Embeddings deliberately bypass it, because
compressing the text would move the vector the answer cache keys on.

`deploy/docker-compose.yml` turned out not to parse at all — unquoted
`${VAR:-default}` inside a flow mapping, plus a duplicate `ENVIRONMENT` key.
Nothing read the file, so nothing said so. `make test` validates it now.

**Session 7 — the answer cache.** A per-squad cache of `ask_codebase`
answers, keyed on a new per-project index epoch that the indexer bumps after
every successful run. Exact-question tier first, semantic tier only when an
embedding model is set. ADR-0009 records the vector-store research: pgvector
is the eventual answer, Qdrant is not, and neither is justified at the current
candidate-set size — with the number and the metric that would change that.

Adding the second migration exposed that revision one built the schema from
the live models, so it created revision two's tables and revision two then
failed. Revision one is now transcribed, and a test compares the migrated
schema to the models in both directions.

**Session 6 — environments and promotion.** ADR-0008, `docs/environments.md`,
`MIGRATE_ON_START`, `ENVIRONMENT`, per-environment Helm values examples, image
publishing from `dev`, a release workflow, and `scripts/check-chart.sh`.

Bringing the chart up to date turned up four things that were broken rather
than merely missing, all left behind by the move to database configuration:
the chart supplied no `DATABASE_URL` at all, it pointed both deployments at
one image although gateway and indexer are separate images, `scripts/dev.sh`
and the CI smoke started services with no database, and four
administrator-editable `indexer.*` settings were read by nothing. All four are
fixed and covered.

**Session 5 — configuration in the database.** Added `common/`: schema,
Alembic migrations, Fernet-encrypted secrets, Argon2id administrator
accounts, the configuration store and `repo-mcp-admin`. Both services now read
configuration from PostgreSQL through a generation-cached store; the gateway
gained an `/admin` API. Compose ships PostgreSQL plus an `init` container, and
`DATABASE_URL` switches to an external instance. Also adopted the
`feature/`/`bugfix/`/`hotfix/` branch convention, enforced by
`scripts/check-branch.sh`.

The store deliberately produces the same document shapes the YAML files had,
so `TenantRegistry.from_dict` and the whole authorization path were untouched
— which is why every existing test still applies.

**Session 4 — agent working agreement.** Added `AGENTS.md` (the binding
contract), `CLAUDE.md` (a thin Claude-specific layer that defers to it), this
memory bank, and `docs/code-standards.md`. A CI job now checks that every
command documented in `AGENTS.md` actually exists as a `make` target, because
a working agreement that drifts from reality is worse than none.

**Session 3 — branching and secrets.** Adopted `main`/`dev`. Added
`scripts/check-secrets.sh` as a pre-commit hook plus a CI job, and
`deploy/.env.example`. Verified in both directions: zero false positives on
the real tree, every planted secret caught, and a live `git commit` blocked.

**Session 2 — operations.** Scripts (`setup`, `test`, `dev`, `debug`,
`stack`, `smoke`, `e2e`), Prometheus metrics on both services, hardened
multi-stage images, and a Helm chart. `make debug` immediately found a real
bug — a missing engine binary surfaced as HTTP 500 — now fixed and covered by
a test.

**Session 1 — the platform.** Gateway, indexer, three-layer authorization,
role model, provider connectors for GitHub/GitLab/Bitbucket, LiteLLM
composite tools, and the documentation set including five ADRs.

## Decisions made recently, and why

**`AGENTS.md` is the contract; `CLAUDE.md` defers to it.** Two copies of the
same rules drift, and then neither is trusted. Tool-specific files stay thin.

**The chart refuses to render a gateway HPA without `ReadWriteMany`.** A
replica without the graph stores does not fail loudly — it answers from an
empty graph, which reads as a code bug. Failing at template time costs a
minute; the alternative costs an afternoon.

**Production refuses a mutable image tag, rather than warning.** Same
reasoning as the HPA guard: `latest` in production makes "which commit is
running" unanswerable at the moment it matters, and turns a rollback into a
rebuild.

**Migrations are automatic in dev and deliberate in production.**
`MIGRATE_ON_START` defaults to false. Auto-migration is convenient until the
first migration that takes a table lock, or the first older replica starting
against a newer schema during a rollback.

**`indexer.replicaCount` is pinned to 1.** The queue and its per-project locks
are in-process. Horizontal indexing needs a shared queue first.

**Documentation says "the engine", not the upstream product name.**
Attribution lives in `NOTICE`, and `docs/engine.md` is the single page that
discusses engine internals — with source references, so claims are checkable.

## Watch out for

- **`main` is at the initial commit.** Do not assume it contains the code.
- **The engine binary is usually not installed locally.** Everything except
  tool execution works; the error message says so explicitly. To get it:
  `curl -fsSL <releases>/latest/download/codebase-memory-mcp-linux-amd64.tar.gz`,
  unpack, put it on PATH. `make screenshots` needs it.
- **`deploy/tenants.yaml` and `deploy/scan.yaml` are local and ignored.** Edit
  the `.example` files to change the shipped defaults. They are seed documents
  for `repo-mcp-admin import`, not runtime configuration.
- **`deploy/helm/values-*.yaml` is ignored too**; the `.example` files beside
  them are the tracked reference.
- **`helm` cannot be installed in every sandbox** (the download is sometimes
  blocked). `make check-chart` covers the templates without it; CI still runs
  the real `helm lint` and `helm template`.
- **Two things are designed but not built:** the web UI and graph history.
  `progress.md` and `docs/roadmap.md` both say so — keep it that way.

## Suggested next steps

Roughly in order of value per unit of effort:

0. **Wire up the `org/public` shared layer.** The `cross-repo-intelligence`
   mode and the `structural_only` tenant flag both exist; the nightly job that
   builds the layer does not. Small job, unlocks cross-squad topology answers.
3. **Durable job queue** (Redis or NATS) with per-project leases, so the
   indexer can run more than one replica.
4. **Graph history**, per [ADR-0004](../docs/adr/0004-graph-history.md):
   publish snapshots to object storage and add a diff service.
5. **Web UI.** Largest chunk by far, and effectively its own product. Needs a
   read API and a rendering strategy that survives large graphs.

Before starting any of these, read
[systemPatterns.md](systemPatterns.md) — items 3 and 4 touch invariants.
