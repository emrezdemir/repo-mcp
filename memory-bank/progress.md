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

**Web interface** (`/ui`)
- Search asks the engine about the whole project, not just the drawn subset.
  Verified by filtering every node out and searching for a symbol the engine
  knows: it is offered under "Elsewhere in this project", opens with its
  location and real source, and says why its connections are absent.
- Ask: `ask_codebase` from the browser, verified end to end against a
  stand-in model backend — 16,894 characters of graph evidence reached it and
  the answer came back citing a qualified name. Both refusal paths verified
  too: no backend, and a backend with no key.
- Refusals are shown rather than swallowed, and controls the platform would
  refuse are disabled with the reason on them. Verified by putting the
  payments squad on structure-only and watching the graph still draw while
  the source button explained itself.
- Upstream's `graph-ui`, adopted at d6be58ef and pointed at `/mcp`. Driven in
  a real browser end to end against a real indexed project (854 nodes, 4454
  edges): sign-in, the project list, the 3D graph rendering through the
  authorized layout proxy, and all eight administrative sections. No console
  errors.
- The layout proxy verified against the real engine: 401 without a token, the
  platform's own refusal by name for another squad's project, and the engine's
  port refusing every address but loopback.
- Authorization Code with PKCE against a stand-in provider signing RS256
  tokens the gateway verifies through its ordinary JWKS path. Redirect out and
  back, code exchanged, groups claim mapped to role and squad, code stripped
  from the address bar, refresh before expiry, sign-out clearing storage. Also
  verified: a code with no matching state is refused, and a provider error
  reaches the screen.
- React 19 and Three.js, built by Vite at image build time; the build output
  is not committed.
- 21 tests over `/api/auth`, `/api/session` and static serving, including
  path traversal.

**Identity**
- The bundled Keycloak realm imports: nine groups, a public browser client
  with PKCE, a service client, and the group and audience mappers. Verified
  against a real Keycloak 26 — realm imported, user created by
  `scripts/keycloak-user.sh`, signed in through the browser, and the token's
  `groups` and `aud` claims mapped to the expected role and squad. A user in
  `squad-checkout` sees none of the payments squad's graph.

**Administration**
- `repo-mcp-admin` and the console cover the same operations through the same
  functions: squads, roles, connectors, secrets, settings, audit,
  administrator accounts, answer cache. 18 tests, including one that fails if
  an API operation arrives without a matching command, and one that a CLI
  change reaches a running service through the generation counter.

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
| Container images | Still never built here — no Docker daemon. The engine download and the pip install were each reproduced outside Docker against the real release, and CI builds the image itself |
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
| The image build fetched the engine from a URL that has never existed — the release ships a `.tar.gz`, not a bare binary | CI, on the first run that got that far | Fetch and unpack the archive, verified against the release's own `checksums.txt` |
| The image never copied `common/`, so pip looked for `repo-mcp-common` on PyPI | CI, once the engine download stopped failing first | Both projects copied into the build context and installed in one pip run |
| Eight shellcheck warnings, one a `cd` whose failure would have run the next command against the wrong tree | CI | Fixed; `make test` runs shellcheck now |
| `deploy/docker-compose.yml` did not parse: unquoted `${VAR:-default}` in a flow mapping, and a duplicate `ENVIRONMENT` key | Running `docker compose config` while adding a service | Quoted, deduplicated, and `make test` validates the file now |
| Migration 0001 built the schema from the live models, so it created 0002's tables and 0002 then failed | Adding the second migration | 0001 transcribed explicitly, plus a test comparing the migrated schema to the models |
| Four administrator-editable `indexer.*` settings were read by nothing | Checking which chart values were still real | The indexer reads them from the store, re-reading the rescan interval each pass |
| A capability gate added in session 12 hid the button `NodeDetailPanel`'s test clicks, so CI's `web interface` job had been red ever since and nobody looked | Running `npm test` while adding a test beside it | The test mocks a caller whose role may read source; it asserts source is escaped rather than injected, which is worth keeping |
| Nothing confirmed a connector worked: provider, container name, token scope and patterns all fail the same way — silently, hours later | Asked to make adding a connector from the interface good | `connector check` on both surfaces, running real discovery and naming which of the four is wrong |
| The Pages site 404'd while the build job was green: the `github-pages` environment admits the default branch only, and the workflow published from `main` while the default is `dev` | The maintainer reporting the URL, twice | Publish from whichever branch is the default; other branches skip visibly instead of failing with no steps and no message |

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
