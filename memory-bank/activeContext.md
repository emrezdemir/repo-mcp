# Active context

**Last updated:** 2026-08-02
**Branch:** `feature/answer-cache`, off `dev`

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
  tool execution works; the error message says so explicitly.
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

0. **Headroom as an updatable plugin** — pinned image tag, a DB setting to
   enable it, structural tool outputs only. Never `get_code_snippet`.
1. **Wire up the `org/public` shared layer.** The `cross-repo-intelligence`
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
