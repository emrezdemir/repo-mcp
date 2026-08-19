# Progress

**Last updated:** 2026-08-19

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
  administrator accounts, answer cache. Tests include one that fails if an API
  operation arrives without a matching command, and one that a CLI change
  reaches a running service through the generation counter.
- `connector check` on both surfaces: runs real discovery against the provider
  and reports what it can see, or names which of provider / container name /
  token / patterns is wrong. Verified against a stand-in GitHub API through
  the real HTTP endpoint and the real command — six failure paths, each with
  its own sentence. Exits non-zero when the connector does not work.

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
- The local no-Docker path has a lifecycle of its own now: `make dev-start`
  returns once `/healthz` answers (about two seconds), `make dev-stop` takes it
  down through the supervisor's exit trap, `make dev-logs` follows it. Measured
  on macOS: 2.1 s up, a real `tools/list` against the real engine, 0.5 s down,
  no stray process. Starting twice is refused, a stale PID file is recognised
  rather than signalled, and `--stop` checks the command line behind the PID
  before killing anything — verified by pointing it at PID 1 and watching it
  decline.
- **`make smoke` passes 14 of 14** against the real engine and a real graph
  (macOS). It had never been run against a real engine before, and two of its
  own defects were hiding behind that — see Fixed along the way.
- `make setup` / `test` / `verify` / `dev` / `debug` / `stack` / `site` /
  `check-secrets` — all run end to end in a clean checkout **here**. Note the
  qualifier: `make setup` ran cleanly in this sandbox for twelve sessions and
  still failed on the maintainer's Ubuntu server, because `venv` ships
  separately there. A green run in one environment is not a green run.
- `make setup ARGS=--config-only` writes configuration and installs no Python
  at all, for a server that only runs the Docker stack.
- Secret scanning: verified in both directions — zero false positives across
  the tracked tree, every planted secret caught, and a live commit blocked by
  the hook.
- 175 Python tests (91 common, 63 gateway, 21 indexer) and 34 interface tests,
  `ruff` clean. `make test` runs all of them now — the interface suite used to
  run in CI only.
- **`make verify` passes on macOS 26 / Apple Silicon**, whole: three test
  suites, the interface's 34, the example configuration, `docker compose
  config` with and without every profile, shellcheck, the documentation rules,
  the chart, the version check and the secret scan. `make setup` works there
  end to end too — three virtualenvs, `deploy/*.yaml`, the wizard's `.env`, and
  the configuration verified through the real loaders.

**Image publishing and releases**
- CI publishes `dev-<sha>` and `dev-latest` for both services to GHCR on every
  push to `dev`, after the image it just built proved it starts. Verified
  against the registry API: both packages resolve anonymously, `dev-latest` is
  present alongside a dozen `dev-<sha>` tags, so `make up ARGS=--pull` has real
  images to fetch. **Multi-architecture** since 0.4.3 — `linux/amd64` and
  `linux/arm64` — and the release asserts both are in the published manifest
  rather than trusting the build to have honoured the list. Verified beyond the
  manifest: the arm64 image was pulled on an Apple Silicon Mac and run, and
  `codebase-memory-mcp --version` — the command that hung forever on the amd64
  image — exits 0 with `codebase-memory-mcp 0.10.5`. `repo-mcp-admin` and the
  Python application import in the same image. The arm64 leg costs about ten
  minutes of CI per push to `dev`.
- **`v0.4.1` was the first version tag this project ever pushed**, and the
  release path is exercised end to end now: the guard (semver, the tag is on
  `main`, `VERSION` agrees, the changelog has a section), `:vX.Y.Z` and
  `:latest` for both services, and the chart packaged to
  `oci://ghcr.io/emrezdemir/charts`. All four jobs green.
- The release also **creates a GitHub Release** from the changelog's own
  section. It did not until 0.4.2 — see Fixed along the way; that gap is why
  `make upgrade` and the update banner could never have worked.

**Documentation**
- Architecture, engine constraints (with source references), roles and
  permissions, deployment, scaling, development, branching, roadmap,
  administration, web interface, code standards — 12 documents and 11 ADRs.
- All of it built onto the project site from the same markdown by **Docusaurus**
  (`docs-site/`) — a sidebar, breadcrumbs and prev/next; the assembled site's
  local references all resolve (1037 checked). The site is live and publishes
  from the default branch.
- `AGENTS.md`, `CLAUDE.md`, this memory bank.

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
| Helm chart install from the registry | The chart is packaged and pushed to `oci://ghcr.io/emrezdemir/charts` by a real release now, but no `helm install` has ever pulled it from there |
| The bootstrap hook Job | Never run in a cluster; the same `repo-mcp-admin init` command was run directly |
| End-to-end script | Never run; needs Docker |
| LDAP federation | A real directory. Keycloak 26 itself *was* stood up here — the realm imported, groups and both clients created, a user made by `scripts/keycloak-user.sh` — but no LDAP server has ever been federated into it, so group mapping from a directory is unproven |
| Headroom | Never started. The routing, the fallback and the embedding bypass are unit-tested against a mock transport; no Headroom container has run, and its own upstream configuration is its documentation, not ours |
| The answer cache's semantic tier | A real embedding model. The storage, scoring, isolation and invalidation are unit-tested with synthetic vectors; no `/embeddings` call has been made |
| First-run in the browser | A real browser against a running gateway. The router is unit-tested — 7 gateway tests, denial path included — but the `/setup` redirect, `init` deferring admin creation, and `ensure_admin` against a live database have not been run end to end. See ADR-0012 |
| Podman | A real Podman host. The engine abstraction resolves and the Compose file validates through `compose()` on Docker here; the `podman compose` / `podman-compose` branch is the same code but has not run against Podman |

**First real deployment should start here.** These are where surprises live.

## Broken

Nothing outstanding. Session 15 found four and fixed all four — kept here
because the *reason* they existed is the reusable part.

Three were one bug wearing three hats. macOS ships **bash 3.2**, where
expanding an empty array under `set -u` is a fatal *unbound variable* rather
than nothing; bash 4.4 fixed it, so no Linux host and no CI runner would ever
have shown it. `make test`, `make up` and `make setup` each died before doing
any work — `test.sh` with no pytest arguments, `stack.sh` with no extra compose
arguments, `wizard.sh` with an answer set selecting no optional profile. All
three now use `${arr[@]+"${arr[@]}"}`; `${#arr[@]}` was always safe, and
`dev.sh:143` had guarded its `kill` correctly all along. The rule is in
[code-standards.md](../docs/code-standards.md) §3 now.

The fourth was universal and older: **`make site` built nothing** on any
platform, because the target was never `.PHONY` and a `site/` directory
satisfies it. `check-docs.sh` did not catch it — it checks that a make target
exists and is documented, not that it does anything. Both are `.PHONY` now.

One gap of the same family closed with them: `make test` now runs the **34 web
interface tests**, which only CI had ever run. That is precisely how session
13's `NodeDetailPanel` regression sat red for a whole session. They skip with a
message when Node or `node_modules` is absent, so a Python-only checkout is
unaffected.

The fifth defect was one this file had already written off as a cost decision,
and the write-off was wrong. The published images were `linux/amd64` only, and
that was recorded as "Apple Silicon runs the stack emulated" — slower, not
broken, so not worth doubling CI build time over. **Running it disproved that.**
In the same amd64 image on Apple Silicon, `sh -c 'echo hello'` exits 0, and
`codebase-memory-mcp --version` blocks forever — five minutes, twice, and still
`running`. Emulation works; the engine binary does not. So `make up
ARGS=--pull` on a Mac produced a stack that comes up healthy and times out on
every tool call, which is about the worst failure shape available. Both
workflows publish `linux/amd64,linux/arm64` from 0.4.3, and the release asserts
both are in the manifest — the runner is amd64, so running the image only ever
proved amd64.

Worth keeping as a lesson rather than a line item: the claim "it works,
emulated" was written down without ever being run, and it survived a review
because it was plausible. It cost nothing to check and the check reversed the
decision.

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
| `make setup` guarded venv creation on `[[ -d .venv ]]`, and on Debian/Ubuntu a failed `python3 -m venv` leaves the directory behind — so a first failure became permanent, and no `venv` or `pip` exit status was checked | The maintainer running it on a fresh Ubuntu server | Preflight `ensurepip` check naming the package, test the pip binary rather than the directory, rebuild a half-made environment, check every exit status |
| gateway and indexer could not install: they depend on `repo-mcp-common`, whose path is in `[tool.uv.sources]` (uv-only), so pip looked for it on PyPI and failed with "No matching distribution found" | The maintainer running `make setup` on the Ubuntu server | Install the local `common` into the gateway and indexer venvs first, so pip sees the dependency already satisfied |
| A working tree at `//home/...` (VirtualBox shared folder) broke two tools: pip read the leading `//` as a URL host ("file:// scheme is supported only on localhost"), and pytest's terminal summary raised `relative_to()` because `//home/...` is not under `/home/...`, crashing a run whose tests had passed | `make setup`, then `scripts/test.sh`, on the Ubuntu server | `lib.sh` collapses `REPO_ROOT` to a single leading slash, so every script agrees on the path; on Linux `//x` and `/x` are the same directory |
| `check-docs.sh` read the README section under `## Documentation`, and the Turkish README's heading is `## Belgeler` — so it matched nothing and passed | Moving the README's links to the site and wondering why the check stayed green | Reads both READMEs whole, resolves site URLs back to `docs/*.md`, and fails when it matches implausibly few links |
| A capability gate added in session 12 hid the button `NodeDetailPanel`'s test clicks, so CI's `web interface` job had been red ever since and nobody looked | Running `npm test` while adding a test beside it | The test mocks a caller whose role may read source; it asserts source is escaped rather than injected, which is worth keeping |
| Nothing confirmed a connector worked: provider, container name, token scope and patterns all fail the same way — silently, hours later | Asked to make adding a connector from the interface good | `connector check` on both surfaces, running real discovery and naming which of the four is wrong |
| The Pages site 404'd while the build job was green: the `github-pages` environment admits the default branch only, and the workflow published from `main` while the default is `dev` | The maintainer reporting the URL, twice | Publish from whichever branch is the default; other branches skip visibly instead of failing with no steps and no message |
| `release.yml` published images and a chart and stopped, so `/releases/latest` stayed 404 — and both the interface's update banner and `make upgrade` read exactly that endpoint. A flawless release left the whole upgrade path dead | Cutting v0.4.1 for real, then running `make upgrade --check` against it | A `release` job that creates the GitHub Release from the changelog's own section for that version |
| `make upgrade` exited 1 with no message at all when the release check failed: `grep` finds no `tag_name`, and under `set -e` with `pipefail` the assignment ends the script before the line written to explain it | The same run — the error message its author wrote was unreachable | `\|\| true` on the pipeline, not just the `curl`; both paths verified |
| A fresh install could not make **one** tool call: the gateway creates the tenant's cache directory but not its repository root, and the engine refuses to start when `CBM_ALLOWED_ROOT` is not there. The directory is made by the indexer on its first clone, so every squad nothing had indexed yet was dead. The image has the same gap — it creates `/var/lib/repo-mcp/repos`, not the per-tenant directory under it | Installing the real engine and running `make dev` | `os.makedirs(repo_root)` beside the cache one, with a test asserting both exist before the process starts |
| The engine's own reason was read and discarded: stderr went to `log.debug` and nowhere else, so `daemon session context was rejected` became `engine process exited unexpectedly` | The same run — bisecting the environment by hand to recover a message the gateway already had | A bounded tail of the last stderr lines, carried in the error |
| `make dev` printed "JWT verification disabled" and a token, then answered **401** to that token: it sources `deploy/.env` with `set -a`, and `make setup` writes `DEV_INSECURE_AUTH=false` there by default (the stack's identity is Keycloak), which stopped `dev.sh`'s own `${VAR:-true}` default from applying | Running the documented path — `make setup`, `make dev`, curl — on a machine that had done neither before | The shell's value is captured before `.env` is sourced and still wins; the file's does not. The banner now says what is true |
| Every script's `--help` printed raw `#` prefixes on macOS. All 17 stripped the comment marker with `sed 's/^# \\?//'`, and `\\?` is a GNU extension: BSD sed reads it as a literal `?`, matches nothing, strips nothing | Reading `dev.sh --help` while adding to it, and noticing `stack.sh` did the same | `sed -E 's/^# ?//'`, which behaves identically on GNU and BSD — checked against both |
| `make smoke` sent `"params":{\}` on macOS: its default was `${2:-{\}}`, and bash 3.2 keeps the backslash that escapes the brace where bash 4.4+ drops it. Three assertions failed on `-32700 invalid JSON` without naming it | Running `make smoke` against the real engine for the first time | The default is assigned on its own line, which needs no escaping |
| The smoke test's graph queries had always asked about a project called `projects` — it took the project name with `grep -oE '[A-Za-z0-9._-]{3,}' \| head -1` over a JSON answer, and that first match is the key. Not platform-specific; it would fail anywhere the engine actually ran | The same run — the three query assertions failed and the log said `querying project: projects` | Read the name with `jq`, which the script already requires; the grep stays as a fallback for a non-JSON answer |
| The scripts only worked from the repository root: four embed Python with relative paths (`deploy/tenants.yaml`, `sys.path.insert(0, "gateway")`). `dev.sh` died with FileNotFoundError; `debug.sh` reported `tenants.yaml is invalid` one line after confirming it exists, which is a diagnostic tool misdiagnosing its own subject | The maintainer running `./dev.sh` from inside `scripts/` | `lib.sh` moves to the root once for every script; nothing there used the caller's directory. Verified from `scripts/`, `/tmp` and the root |

## Never verified in this environment

Stated plainly so nobody assumes otherwise:

- No Docker build has run here (proxy restrictions). CI covers it.
- `helm` could not be installed here — `get.helm.sh` returns 403 through the
  proxy. `make check-chart` covers the templates without it; CI covers `lint`
  and `template`.
- No image has been pushed to a registry from here, and no release tag has
  been cut. The release workflow's guards are unexercised.
- ~~The engine binary was never available here~~ — **no longer true.** The
  native `darwin-arm64` build was installed on the Mac and driven through the
  gateway end to end: 11 tools listed, a real repository indexed (514 nodes,
  2,232 edges), `search_graph` returning real symbols by BM25, and the project
  allowlist refusing an outside project with `-32001` against the real engine
  rather than a fake. It found three defects in one sitting — see Fixed along
  the way. The unit tests still use the fake engine, and should: it makes the
  awkward paths (timeout mid-stream, unexpected exit, ten concurrent callers)
  testable without the binary.
- No provider was ever contacted for real. Every connector and discovery test,
  including `connector check`, ran against a stand-in GitHub API on loopback.
  The request shapes come from the provider documentation, not from a live
  round trip against github.com.
- **The maintainer is now deploying to a real Ubuntu server.** That is the
  first environment outside this sandbox, and it has already produced one
  defect this sandbox could never have shown (`make setup` and Debian's
  separate `venv` package). Expect more of that class, and prefer their report
  over anything asserted here.
- **macOS is now a second real environment** (macOS 26, Apple Silicon), and it
  immediately produced four defects — see Broken. The pattern holds: every new
  host finds something no amount of reading here would have. Neither Docker
  nor Podman has been used to start the stack on it, so `make up`, the images
  under emulation and `make smoke` are unproven on macOS even once the shell
  bug is fixed.
