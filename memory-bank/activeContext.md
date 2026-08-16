# Active context

**Last updated:** 2026-08-15
**Branch:** `dev`

## Where things stand

Everything the platform promises is built and running. Configuration lives in
PostgreSQL with an administrative API, a first-boot administrator and encrypted
credentials; both services read it at runtime and pick up changes without a
restart. The MCP surface, the three authorization layers, the per-tenant engine
bridge, the answer cache and the composite tools are in place.

The **web interface** is built and is the engine project's own, adopted rather
than written here (ADR-0011). It signs in with OIDC, picks a squad, draws the
graph, asks questions, and administers squads/roles/connectors/secrets/
settings/audit — the same functions `repo-mcp-admin` calls.

The **project site** is live at `emrezdemir.github.io/repo-mcp/`: a hand-written
landing at the root, and the whole reference documentation under `/docs/` built
by **Docusaurus** (`docs-site/`) from the same `docs/` markdown.

Deployment has a shape: branches produce images, images are promoted to
environments, and configuration is never promoted. CI publishes `:dev-<sha>`
from `dev`; a version tag publishes `:vX.Y.Z` and packages the chart. The
publish half is **no longer theoretical**: `ghcr.io/emrezdemir/repo-mcp-gateway`
and `-indexer` carry `dev-latest` plus a dozen `dev-<sha>` tags, and both pull
anonymously — verified against the registry API. No release tag has been cut,
so there is no `:latest` and no `:vX.Y.Z`; nothing defaults to either.

The repository is **public** on GitHub (`emrezdemir/repo-mcp`, MIT, default
branch `dev`). Every push is world-readable the moment it lands — the secret
scan is the gate, and a full history scan for credential shapes and
forbidden paths came back clean.

### Branch state, as of this writing

- `dev` is the **default branch** and carries everything. Head: `58f25bf`.
- `main`, `dev` and `origin/dev` are all at that same commit — zero ahead, zero
  behind. The earlier note here ("main is behind and its CI is red") stopped
  being true and stayed; it is fixed now.
- The maintainer merges `dev` into `main` (a fast-forward, `git push origin
  dev:main`, keeps the two identical) and deletes branches. There is **no
  automatic main→dev sync** any more — `sync-dev.yml` was removed at the
  maintainer's request; `dev` changes only when something is pushed to it.

### Open question for the maintainer

The reference documents under `docs/` are **English**; the landing pages (site
and README) are Turkish. Translating the reference set was raised and not
decided, because it means choosing which language is the source — one English
source rendered to the site, or Turkish as the source with English derived.
Do not start translating without that answer: two hand-maintained copies drift,
which `AGENTS.md` forbids.

## What the last sessions did

**Session 15 — the first run on macOS, and four commits nobody had recorded.**
Two halves.

*The unrecorded commits.* `dev` had moved four commits past what this file
described, all from the maintainer's server run: `make up` learned to pull the
published images rather than build (`ARGS=--pull`, passed through from the
Makefile), `--no-build` was made explicit because some podman-compose versions
build a service that has a `build:` section even on a plain `up`, the Compose
images were fully qualified (`docker.io/library/postgres:16-alpine` — Podman
does not assume Docker Hub for short names), and `docs/deployment.md` gained a
Requirements table after a 25 GB VirtualBox disk ran out mid-build.

*macOS, for the first time.* The whole toolchain was driven on macOS 26 /
Apple Silicon. `make setup` works end to end — three virtualenvs, configuration,
the wizard's defaults — and all **175 Python tests pass** (91 common, 63
gateway, 21 indexer; the 10 gateway skips are the interface not being built).
`check-branch`, `check-secrets --all`, `check-docs`, `check-chart` and
`version --check` all pass.

What did not work was **bash**. macOS ships bash **3.2**, where expanding an
empty array under `set -u` — `"${arr[@]}"` — is an *unbound variable* error
rather than nothing. bash 4.4 fixed it, so Ubuntu never sees this. Three
scripts did exactly that on their ordinary path, and each died before doing any
work: `test.sh:76` (`make test`, `make verify`), `stack.sh:43/47/50`
(`make up`), and `wizard.sh:221` (`make setup` whenever the answers select no
optional profile — external identity with no model backend). All three
reproduced, not inferred, then fixed with `${arr[@]+"${arr[@]}"}` and verified
against every argument shape the callers actually pass.

Separately and on **every** platform: `make site` did nothing. `site` is a
target with no prerequisites and a `site/` directory exists, and the target was
never declared `.PHONY` — `.PHONY: screenshots` sat immediately above it and
covered the wrong name — so make answered `'site' is up to date` and never ran
the build. Nothing caught it because `check-docs.sh` checks that make targets
exist and are documented, not that they run. Both targets are `.PHONY` now.

Two gaps of the same family. `make test` **never ran the 34 web interface
tests** — only CI did, and that is precisely the shape of the defect session 13
found when a capability gate left CI's `web interface` job red for a session
with nobody looking. It runs them now, skipping with a message when Node or
`node_modules` is absent so a Python-only checkout is unaffected. And the
published images are **`linux/amd64` only** (no `platforms:` in either
workflow), so on Apple Silicon `make up ARGS=--pull` runs the whole stack under
emulation — left as it is and documented, because adding arm64 to the matrix
roughly doubles every image build in CI and that is the maintainer's call.

Afterwards `make verify` passes on macOS in full, and the bash-3.2 rule and the
`.PHONY` rule are both written into `docs/code-standards.md` §3 — the point
being that neither CI nor a Linux server can ever catch either one. The test
tables in `AGENTS.md` §7 and `docs/development.md` gained a fifth **Interface**
layer, because `make test` now covers something they did not list.

The work was **cut as 0.4.1** — a fix release, by the standing rule that a
change bumps the version if it warrants one. `scripts/version.sh --set` did
`VERSION`, the three `pyproject.toml`s and the chart; the README badges and the
changelog were done by hand, as always.

*And then the release itself was cut, which found two more.* `v0.4.1` is the
**first version tag this project has ever pushed** — `git push origin dev:main`
then the tag, as `branching.md` describes. All four release jobs went green:
the guard, both images at `:v0.4.1` and `:latest`, and the chart to
`oci://ghcr.io/emrezdemir/charts`. A flawless release — and the upgrade path it
feeds was dead at both ends.

`release.yml` published images and a chart and stopped. But a pushed tag is not
a release to anything that asks GitHub: `/releases/latest` answers **404**
until a Release object exists, and two things we ship read exactly that
endpoint — the interface's update banner and `make upgrade`. Worse, `make
upgrade` did not say so: with no `tag_name` in the body, `grep` exits 1 and
`set -e` with `pipefail` ends the script *at the assignment*, before the line
its author wrote to explain precisely that situation. It exited 1 in silence.

Both are fixed in **0.4.2**: `release.yml` has a `release` job that builds the
notes from the changelog's own section, and the `|| true` in `upgrade.sh` is on
the pipeline rather than only the `curl`. 0.4.1's Release object was created by
hand to close the gap for the version already out. The lesson is the one this
memory bank keeps relearning: a path nobody has run is not a path that works,
and "the release went perfectly" is a claim about the jobs, not about what the
release was for.

**Session 14 — the READMEs, the docs site on Docusaurus, and setup on a real
server.** The READMEs were reshaped to what a reader expects of a landing page:
a header with badges and quick links, and a "why" in flowing sentences rather
than a terse table. The landing's captions, which read as internal notes ("860
lines, better to use as-is than rewrite"), were rewritten as captions.

The reference documentation moved from the hand-rolled `render-docs.py` to
**Docusaurus** in `docs-site/`, for a real docs site — a sidebar, breadcrumbs,
prev/next, and a structure search can sit on. `docs/` stays the single English
source; `docs-site/scripts/sync-docs.mjs` copies it in on every build, rewrites
the links that point outside `docs/` to GitHub, and fails the build if a
document is missing from `sidebars.js`. `build-site.sh` and `pages.yml` build it
with Node; `render-docs.py` and `.site-venv` are gone. The ADR URLs keep their
numbers (`numberPrefixParser: false`), so the links the READMEs and landing
already used still resolve — now as clean `/docs/architecture/` URLs.

`make setup` was fixed for the maintainer's Ubuntu server, the same class as
session 13's venv bug. gateway and indexer could not resolve `repo-mcp-common`
— its path is in `[tool.uv.sources]`, which pip ignores — so the local `common`
is installed into their venvs first. Then, on a VirtualBox shared folder where
`pwd` reports `//home/...`, the leading `//` broke pip (read as a URL host) and
also pytest (its summary's `relative_to()` raised on `//home` vs `/home`,
crashing a run whose tests had passed). The general fix is in `lib.sh`, which
collapses `REPO_ROOT` to one leading slash for every script.

Two onboarding gaps from the same server run: the setup "Next" message and
`deployment.md` said nothing about the web interface, so it was unclear what
had been installed. Both now point at `http://localhost:8080/ui`, say `make up`
starts containers rather than a system service, and note sign-in needs OIDC.
And the landing was trimmed to a showcase — the per-role scenarios and the
four-step install it duplicated from the now-real docs are gone; hero, the 3D
graph, four reasons, the screenshots, a three-line quickstart, then `/docs`.

Then two changes aimed at making the install simple, both driven by the
maintainer standing up the Ubuntu server. **Docker or Podman** are both
supported: `lib.sh` picks whichever is installed (docker preferred), and
`CONTAINER_ENGINE` forces one; `compose()`, the `need` check, `test.sh`'s
Compose check and `make build`/`push` all route through it. And the **first
administrator is created in the browser** — a fresh install printed a generated
password to the `init` log, which was the step new operators missed. Now, with
no administrator, the gateway serves `/setup` (a page it renders itself, no
React change): create the admin once, the platform becomes usable without a
restart, and the door shuts — `/setup` and `POST /api/bootstrap/admin` refuse
once one exists. `init` still creates it server-side when `ADMIN_PASSWORD` is
set (CI, enterprise). ADR-0012 records the trade-off; 7 gateway tests cover it,
denial path included.

And `make upgrade` (`scripts/upgrade.sh`) closes the loop for a self-hosted
install: it reads the latest GitHub release, and — because the stack builds from
source — fetches that tag, checks it out and rebuilds, applying migrations
through `init`. `ARGS=--check` only reports whether an update is available, which
a cron entry or timer turns into a notification; the upgrade itself stays a
confirmed step, and it refuses to run over uncommitted changes.

Two housekeeping changes closed the session. **`sync-dev.yml` was removed** at
the maintainer's request: there is no automatic main→dev sync any more, and a
release is a fast-forward `git push origin dev:main` (branching.md rewritten to
match). And the accumulated work was **cut as 0.4.0** — `VERSION`, the three
`pyproject.toml`s, the chart and the README badges bumped, and the changelog's
`[Unreleased]` finalized as `[0.4.0]`. The **standing rule going forward**:
when a change lands, bump the version if it warrants a release, and update the
docs in the same change.

**Session 13 — the site, the connector check, and four things that were
quietly broken.** A long session; grouped by subject rather than by order.

*The READMEs and the site.* Both READMEs were 699 lines, which is a manual
rather than a landing page. They became 127 each, and everything cut moved to
`site/` — a hand-written landing page in Turkish and English sharing the
interface's palette. Then the whole reference documentation was rendered onto
it too, by `scripts/render-docs.py`: the markdown under `docs/` stays the
single source, and a document missing from that script's `ORDER` fails the
build rather than being published with nothing linking to it. Finally the
Turkish itself, which read as a translation of the English — calqued sentence
shapes, an archaic participle, headings that were not sentences — was
rewritten on the landing page and in the README.

*The connector check.* The connector form existed but left two gaps: the token
secret had to be created on another tab first, and nothing confirmed the
connector worked — a wrong organisation and an expired token both surfaced
hours later as "nothing indexed". `repo-mcp-admin connector check` and a
**Check** button now run real discovery and report it in words; a token can be
stored from the form. Repository discovery moved to `common/` because the
gateway needs it. Verified against a stand-in GitHub API through the real
endpoint and the real command: every failure path returns its own sentence.

*Two branch problems, separate and easy to confuse.* Merging through a pull
request leaves a merge commit on `main` that `dev` never receives, so history
diverged by one commit per release while content stayed identical —
`sync-dev.yml` fast-forwards `dev` after every push to `main`, refusing rather
than forcing if `dev` moved on. Separately, the site 404'd while the Pages
build job was green: GitHub creates the `github-pages` environment with a
branch policy admitting **only the default branch**, and the workflow published
from `main` while the default is `dev`. A job whose environment refuses its ref
runs no steps and fails in one second with no message, so it reads as a build
failure and is not one. It now publishes from whichever branch is the default.

*Four things found broken while doing the above* — worth reading as a pattern,
because three of the four were green:

- `NodeDetailPanel`'s "Show code" test broke when session 12 put the button
  behind `useCan`. CI's `web interface` job had been red since, unnoticed.
- `check-docs.sh` read the README section under `## Documentation`, and the
  Turkish README's heading is `## Belgeler` — so it had been passing without
  checking anything since the README was translated.
- `docs/architecture.md` still said the web UI was "on the roadmap".
- `make setup` guarded venv creation on `[[ -d .venv ]]`, and on Debian and
  Ubuntu a failed `python3 -m venv` leaves the directory behind — so the first
  failure became permanent. Reported by the maintainer from a fresh Ubuntu
  server, the first report from outside this sandbox. Fixed, and
  `--config-only` added: a machine that only runs `make up` needs no
  virtualenvs and should not install a Python toolchain to get a `.env`.

**Session 12 — auditing the adopted interface, and the Ask tab.** Driving
every surface against the real engine found that the interface was hiding
refusals: a squad on the analysis profile cannot call `manage_adr`, and the
dialog opened empty with a save button that did nothing. Refusals now appear
in the platform's own words, and controls it would certainly refuse are
disabled with the reason on them rather than vanishing.

Two more from the same pass: selecting a symbol from the search results only
highlighted a dot in three dimensions, which made the source view effectively
unreachable; and the dialogs could not be closed by keyboard at all.

Then the biggest missing capability. `ask_codebase` is what this platform has
that a local graph viewer does not, and it had no interface. Adding one
exposed that `/api/session` reported only the engine's tools while
`tools/list` also offers the composite ones — so the tab would have been
hidden forever. Both now call one function.

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

- **The repository is public.** Anything pushed to `dev` is world-readable
  immediately, and `dev` is the default branch, so it is what a visitor lands
  on. Run `make verify` before pushing — the secret scan is in it.
- **On macOS the shell is bash 3.2**, and `"${empty_array[@]}"` under `set -u`
  is a fatal *unbound variable* there. Never expand a possibly-empty array
  without guarding it: `${#arr[@]}` is safe, `"${arr[@]}"` and `"${arr[*]}"`
  are not. Ubuntu's bash 5 hides this completely, so CI will not catch it.
- **`main` and `dev` are identical** (both `58f25bf`). The old note here said
  main trailed with a red CI; that has been true and then untrue more than
  once — check with `git rev-list --left-right --count origin/main...HEAD`
  rather than trusting this line.
- **The engine binary is usually not installed locally.** Everything except
  tool execution works; the error message says so explicitly. To get it, fetch
  the archive for **this** machine from the engine's releases —
  `codebase-memory-mcp-linux-amd64.tar.gz` on an Ubuntu server,
  `codebase-memory-mcp-darwin-arm64.tar.gz` on an Apple Silicon Mac (upstream
  publishes darwin and linux, amd64 and arm64) — unpack, put it on PATH.
  `make screenshots` needs it.
- **`deploy/tenants.yaml` and `deploy/scan.yaml` are local and ignored.** Edit
  the `.example` files to change the shipped defaults. They are seed documents
  for `repo-mcp-admin import`, not runtime configuration.
- **`deploy/helm/values-*.yaml` is ignored too**; the `.example` files beside
  them are the tracked reference.
- **`helm` cannot be installed in every sandbox** (the download is sometimes
  blocked). `make check-chart` covers the templates without it; CI still runs
  the real `helm lint` and `helm template`.
- **Graph history is designed but not built.** `progress.md` and
  `docs/roadmap.md` both say so — keep it that way. The web interface was the
  other entry here and is now built (sessions 10–13).
- **`dev` is the default branch.** Anything using a GitHub deployment
  environment — Pages today — is admitted for the default branch only.

## Suggested next steps

**First, two things the fixes left open.**

1. **`make up` has still never been run on macOS.** The shell bug that stopped
   it is fixed and the argument handling is verified against every shape the
   Makefile passes, but no container has been started here — so the images
   under emulation, the healthchecks and `make smoke` are all unproven on this
   host. That is the next thing to actually run.
2. **Multi-arch images, or leave them.** `platforms: linux/amd64,linux/arm64`
   in both workflows is the real fix and the Dockerfile already selects by
   architecture; the cost is roughly doubling every image build in CI, which is
   why session 15 documented the limitation instead of deciding it. The
   maintainer's call.

After that, roughly in order of value per unit of effort:

1. **Engine capability gaps in the interface.** Ranked when the maintainer
   asked and never started: a rich project overview from `get_architecture`
   first, then `explain_change_impact` as a pull request blast radius, then
   `trace_path`.
2. **Wire up the `org/public` shared layer.** The `cross-repo-intelligence`
   mode and the `structural_only` tenant flag both exist; the nightly job that
   builds the layer does not. Small job, unlocks cross-squad topology answers.
3. **Durable job queue** (Redis or NATS) with per-project leases, so the
   indexer can run more than one replica.
4. **Graph history**, per [ADR-0004](../docs/adr/0004-graph-history.md):
   publish snapshots to object storage and add a diff service.

Before starting any of these, read
[systemPatterns.md](systemPatterns.md) — items 3 and 4 touch invariants.
