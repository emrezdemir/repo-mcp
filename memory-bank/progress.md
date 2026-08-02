# Progress

**Last updated:** 2026-08-02

Status vocabulary, used strictly:

| Status | Means |
| --- | --- |
| **Works** | Implemented, tested, and verified by running it |
| **Built, unverified** | Implemented and unit-tested, but never exercised against the real thing |
| **Designed** | An ADR or doc exists. No code. |
| **Broken** | Known defect, with a workaround where one exists |

Nothing is described as working unless it has been run. An optimistic entry
here causes real waste: someone builds on it, finds out, and throws the work
away.

## Works

**Gateway**
- MCP over HTTP: `initialize`, `tools/list`, `tools/call`, `ping`, single and
  batch requests. Verified with live curl round trips.
- OIDC/JWT verification against JWKS, with a JWKS cache that retries once on
  an unknown key id. Development mode with a static token.
- Three-layer authorization: role capabilities ∩ tenant tool profile ∩ project
  allowlist, plus the engine's own profile and per-tenant filesystem roots.
  16 tests, including every denial path.
- Engine bridge: one process per tenant, idle reaping, timeout teardown and
  recovery, serialised concurrent callers. 8 tests against a fake engine.
- A missing engine binary returns a named JSON-RPC error, not an HTTP 500.
- Structured audit record per call, including denials. Verified in live logs.
- Prometheus metrics with bounded label cardinality.

**Indexer**
- Discovery for GitHub organisations, GitLab groups (nested subgroups) and
  Bitbucket workspaces or projects, with include/exclude globs.
- Webhook signature verification and payload normalisation for all three
  providers.
- Queue: per-project serialisation, burst coalescing, a failing job not
  killing its worker. 8 tests.
- Scheduled rescan and a CI trigger endpoint.
- Prometheus metrics.

**Configuration database**
- Schema, Alembic migrations, and a store that produces the same document
  shapes the YAML files had, so no authorization code changed. 32 tests.
- Bootstrap: schema upgrade, first administrator, idempotent YAML import that
  moves token values out of the environment into encrypted storage.
- Admin API verified live: login rejects a wrong password, requires a bearer
  token, creates a squad that takes effect with no restart, refuses an unknown
  tool profile and a clashing LDAP group, keeps secret values out of every
  response, and records an actor for each change.
- Argon2id passwords, Fernet-encrypted credentials.

**Tooling**
- `make setup` / `test` / `dev` / `debug` / `stack` / `check-secrets` — all run
  end to end in a clean checkout.
- Secret scanning: verified in both directions — zero false positives across
  the tracked tree, every planted secret caught, and a live commit blocked by
  the hook.
- 50 unit tests, `ruff` clean.

**Documentation**
- Architecture, engine constraints (with source references), roles and
  permissions, deployment, scaling, development, branching, roadmap, 5 ADRs.
- `AGENTS.md`, `CLAUDE.md`, this memory bank, code standards.

## Built, unverified

These are implemented and unit-tested, but have never run against the real
external system. Treat their behaviour as unproven.

| Thing | Never exercised against |
| --- | --- |
| Provider discovery | A real GitHub org, GitLab group or Bitbucket workspace — pagination and rate limits in particular |
| Webhook endpoints | A real webhook delivery from any provider |
| LiteLLM composite tools | A live LiteLLM proxy |
| Container images | Never built here; CI builds them |
| PostgreSQL | Everything was exercised against SQLite. The schema and migration are the same, but no PostgreSQL server has run here |
| The `init` Compose container | Never started; the same commands were run directly |
| Helm chart | Never rendered by `helm`; `make check-chart` checks templates against `values.yaml`, and CI runs `helm lint` and `helm template` |
| Image publishing and the release workflow | No push to a registry has happened; the tag guard, the packaged chart and the `dev-<sha>` publish are all unexercised |
| The bootstrap hook Job | Never run in a cluster; the same `repo-mcp-admin init` command was run directly |
| End-to-end script | Never run; needs Docker |
| Keycloak/LDAP federation | Documented, never stood up |
| Headroom | Never started. The routing, the fallback and the embedding bypass are unit-tested against a mock transport; no Headroom container has run, and its own upstream configuration is its documentation, not ours |
| The answer cache's semantic tier | A real embedding model. The storage, scoring, isolation and invalidation are unit-tested with synthetic vectors; no `/embeddings` call has been made |

**First real deployment should start here.** These are where surprises live.

## Designed, not built

| Thing | Design |
| --- | --- |
| Web UI: codebase map and manual search | [roadmap.md](../docs/roadmap.md) §Next 1. Largest remaining chunk; the upstream visualiser cannot be reused (localhost-bound by construction) |
| Graph history / before-and-after | [ADR-0004](../docs/adr/0004-graph-history.md). Retained snapshots plus a diff service |
| Synced gateway replicas | [ADR-0005](../docs/adr/0005-storage-topology.md) topology 3. Removes shared storage from horizontal scaling |
| Durable job queue | Needed before `indexer.replicaCount > 1` |
| `org/public` shared layer | The mode and the tenant flag exist; the nightly job that builds it does not |
| On-demand branch indexing | Needs ephemeral workers, a TTL cache and a per-user quota |
| Chatbot adapter | The MCP endpoint already serves anything speaking MCP |

## Known limitations

Not bugs — consequences of decisions, recorded so nobody rediscovers them.

- **`indexer.replicaCount` must stay 1.** In-process queue and locks.
- **Gateway horizontal scaling needs `ReadWriteMany`**, on a filesystem where
  SQLite WAL locking is correct. Not NFS. The chart refuses the unsafe
  configuration rather than rendering it.
- **`Recreate`, never `RollingUpdate`.** Mixed engine builds sharing a cache
  root fail the admission barrier.
- **No graph history.** The engine stores only the current graph.
- **Embeddings cannot be redirected.** Compiled into the engine binary.
- **A shared layer lags** (nightly), acceptable for topology questions.
- **`WEB_CONCURRENCY` must stay 1.** Each uvicorn worker would spawn its own
  engine process per tenant.

## Fixed along the way

| Defect | Found by | Fix |
| --- | --- | --- |
| Missing engine binary surfaced as HTTP 500 | `make debug` | Named `CbmError`, with a regression test |
| A freshly bootstrapped database crashed the gateway | Starting it against an empty database | An empty tenant registry is valid; `/readyz` warns instead |
| A malformed dummy password hash raised instead of returning false | The authentication test | A real dummy hash, and `VerificationError` is caught |
| `readme = "../README.md"` rejected by setuptools | `make setup` | Per-service READMEs |
| `:ro` cache mount would break SQLite WAL readers | Review | Read-write mount; writes prevented by the tool profile instead |
| `grep` treating `-----BEGIN` as an option | Testing the scanner | `grep -- "$pattern"` |
| The chart supplied no `DATABASE_URL`, so an install could not have started | Reading the chart while adding environments | Database, secret key and environment label added; ConfigMap removed |
| The chart pointed both deployments at one image | The same read | Repository is a base, component is a suffix — matching CI |
| `scripts/dev.sh` and the CI smoke started services with no database | Running `make dev` | `dev.sh` creates and seeds a local SQLite database; CI runs against PostgreSQL |
| `deploy/docker-compose.yml` did not parse: unquoted `${VAR:-default}` in a flow mapping, and a duplicate `ENVIRONMENT` key | Running `docker compose config` while adding a service | Quoted, deduplicated, and `make test` validates the file now |
| Migration 0001 built the schema from the live models, so it created 0002's tables and 0002 then failed | Adding the second migration | 0001 transcribed explicitly, plus a test comparing the migrated schema to the models |
| Four administrator-editable `indexer.*` settings were read by nothing | Checking which chart values were still real | The indexer reads them from the store, re-reading the rescan interval each pass |

## Never verified in this environment

Stated plainly so nobody assumes otherwise:

- No Docker build has run here (proxy restrictions). CI covers it.
- `helm` could not be installed here — `get.helm.sh` returns 403 through the
  proxy. `make check-chart` covers the templates without it; CI covers `lint`
  and `template`.
- No image has been pushed to a registry from here, and no release tag has
  been cut. The release workflow's guards are unexercised.
- The engine binary was never available here; the bridge is tested against a
  fake engine that speaks the same protocol.
