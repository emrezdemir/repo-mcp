# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.3] - 2026-08-16

### Fixed

- **The published images now carry `linux/arm64` as well as `linux/amd64`.**
  Neither workflow set `platforms:`, so both were built on an amd64 runner and
  published amd64-only — which made `make up ARGS=--pull` produce a **broken
  stack on Apple Silicon**, not a slow one. The failure is worth describing
  because it does not look like an architecture problem: the container starts,
  a shell inside it runs fine, and `codebase-memory-mcp --version` then blocks
  forever under emulation. The one thing the image exists to carry is the one
  thing that does not run. Measured here, not assumed — `sh -c 'echo hello'`
  exited 0 in the same image that hung the engine for five minutes, twice.

  The release additionally **asserts** both architectures are in the published
  manifest. The runner is amd64, so running the image only ever proved amd64,
  and an arm64 variant silently going missing is exactly the regression nobody
  would notice until a Mac pulled it.

### Changed

- **Supported platforms are stated plainly**: Linux and macOS, amd64 and arm64
  — including Apple Silicon and ARM servers. Windows is not supported and there
  is no plan for it. `docs/deployment.md` and `docs/development.md` say so, and
  say what an architecture mismatch looks like when it happens, because "healthy
  stack, every tool call times out" is not a symptom anyone would trace back to
  an image manifest.

## [0.4.2] - 2026-08-16

Both of these were found by cutting 0.4.1 for real — the first version tag this
project has ever pushed. The release itself went perfectly and the upgrade path
it is supposed to feed was dead at both ends.

### Fixed

- **A release now creates a GitHub Release.** `release.yml` published the
  images and pushed the chart, and stopped. But a pushed tag is not a release
  to anything that asks GitHub: `/releases/latest` answers **404** until a
  Release object exists — and two things we ship read exactly that endpoint,
  the interface's update banner (`gateway/app/updates.py`) and `make upgrade`
  (`scripts/upgrade.sh`). So a perfect release left both dead. The workflow has
  a `release` job now, taking the notes from the changelog's own section for
  that version rather than a second copy that would drift.
- **`make upgrade` said nothing when the check failed.** With no release
  published the response body has no `tag_name`, `grep` exits 1, and under
  `set -e` with `pipefail` the assignment itself ended the script — silently,
  exit 1, never reaching the line written to explain precisely that. The
  message it was supposed to print ("offline, rate-limited, or none is
  published yet") is reachable now. Both paths verified: against the real
  release, and against an empty response.

## [0.4.1] - 2026-08-16

A fix release. Three of the commands the documentation opens with did not run
on macOS at all, and one did nothing on every platform.

### Fixed

- **`make test`, `make up` and `make setup` ran on macOS at all.** All three
  died before doing any work, with `unbound variable`, and all three were the
  same bug: macOS ships bash 3.2, where expanding an *empty* array under
  `set -u` — `"${arr[@]}"` — is fatal rather than expanding to nothing. bash
  4.4 fixed it, so no Linux host and no CI runner had ever shown it.
  `scripts/test.sh` (no pytest arguments), `scripts/stack.sh` (no extra
  compose arguments) and `scripts/wizard.sh` (an answer set selecting no
  optional profile) are guarded now, and the rule is written down in
  `docs/code-standards.md` §3 so the next script does not repeat it.
- **`make site` built nothing** — on every platform, not just macOS. The target
  was never declared `.PHONY` and a `site/` directory exists, so make decided
  it was satisfied and answered `'site' is up to date`. The stray
  `.PHONY: screenshots` line sat above it and covered the wrong target.
- `make up ARGS=--pull` now works: the `up` target dropped `$(ARGS)`, so the
  `--pull` flag never reached `stack.sh` and the stack built anyway. `make down`
  and `make logs` pass `ARGS` through too. `--pull` also passes `--no-build`, so
  a podman-compose that would build a service with a `build:` section on plain
  `up` does not.
- The Compose images are fully qualified (`docker.io/library/postgres`,
  `docker.io/ollama/ollama`), so Podman resolves them — it does not assume
  `docker.io` for a short name the way Docker does, and failed with "short-name
  did not resolve ... no unqualified-search registries" without it.

### Changed

- **`make test` runs the web interface's 34 tests.** They existed and only CI
  ran them, which is exactly how a capability gate added in one session left
  CI's `web interface` job red through the whole of the next one with nobody
  looking. They are skipped — loudly, saying what to run — when Node or
  `gateway/webui/node_modules` is absent, so a Python-only checkout is not
  forced to install a second toolchain.
- **macOS is documented as a development host.** `make setup`, the full test
  suite and every check script run there; `docs/development.md` says what
  differs (bash 3.2, and `linux/amd64` images running emulated on Apple
  Silicon), and `docs/deployment.md` says plainly that it is not what a
  deployment should sit on.
- The deployment docs gained a **Requirements** table — CPU, RAM and free disk
  for pulling versus building, and for the bundled models — after a 25 GB VM
  kept running out of space building from source. The "what it is" opening in
  both READMEs was softened from a sweeping claim to a plainer one.

## [0.4.0] - 2026-08-03

### Added

- **A project site**, at `site/`, published to GitHub Pages by
  `.github/workflows/pages.yml`. Turkish and English, sharing one stylesheet
  that takes its palette from the interface's own, so the site and the product
  look like the same thing. It is a showcase, not a manual: the hero, the 3D
  graph, four reasons, the screenshots at a size worth looking at, and a
  three-line quickstart — the detail lives in the docs rather than in a second
  copy of them.

  The landing is hand-written HTML — a few pages that change a few times a
  release do not repay a toolchain of their own. `scripts/build-site.sh`
  assembles it with `docs/images/` and the built documentation into `_site/`,
  so the screenshots have one copy in git and a local preview is what is
  published. The workflow fails if any page references a file that is not there,
  and turns Pages on for the repository itself rather than relying on a settings
  change nobody remembers to make.
- **An Ask tab.** `ask_codebase` is the thing this platform has that a local
  graph viewer does not, and it had no interface. It runs `get_architecture`
  and `search_graph` first and answers from what they returned, citing
  qualified names, so the model is never asked to guess the graph. Verified
  against a stand-in model backend: 16,894 characters of real graph evidence
  reached it and the answer came back with a citation.
- **`GET /api/ui-config`**, backed by a new `ui.language` setting, so an
  installation can pin the interface's language instead of following the
  browser. The interface asked for this endpoint on every load and got a 404.
- **A connector can be checked before it is trusted.** Configuring one is four
  things that must all be right at once — the provider, the container name, a
  token with the right scope, and patterns that keep something — and until now
  none of them was confirmed when it was typed. A wrong organisation and an
  expired token produced the same symptom hours later: nothing indexed, with
  no indication which of the four was wrong.

  `repo-mcp-admin connector check NAME` and a **Check** button on the console's
  connector form now run real discovery against the provider and report what
  came back — `34 of 41 repositories would be indexed`, with the names — or
  the reason, in words that name what to change: the token was refused, no
  such organisation, the patterns keep none of them. Read-only and bounded;
  the console's version runs against what is on screen rather than what is
  stored, and writes nothing. The command exits non-zero when the connector
  does not work, so a deployment script can use it.

  A token can also be stored from that form now, instead of leaving for the
  Secrets section and losing everything typed so far.

  Repository discovery moved from `indexer/app/providers.py` to
  `common/repo_mcp_common/providers.py`: the gateway needs it to answer this,
  and duplicating three provider clients to avoid moving one file would be the
  worse trade.
- **`make setup ARGS=--config-only`**, for a server that will only run
  `make up`. It writes `deploy/.env` and the two YAML files and installs no
  Python packages at all — the stack is entirely containers, and the
  virtualenvs exist for developing and testing here. Without it a deployment
  had to install a Python toolchain to produce a `.env` file.
- **Docker or Podman.** The scripts detect which engine is installed — Docker
  preferred, Podman the fallback — so `make up`, `make build`, `make down` and
  the rest run on either. `CONTAINER_ENGINE=docker|podman` forces one. Podman
  needs a compose implementation (`podman compose` on 4.1+ or `podman-compose`);
  every published port is above 1024, so rootless Podman works unprivileged.
- **The first administrator is created in the browser.** A fresh install used to
  print a generated password to the `init` container's log, so the first thing a
  new operator did was grep a log. Now the interface shows a one-time setup
  screen on first open — choose a username and password, and it creates the
  administrator, after which the platform is usable without a restart. It is a
  one-time door: once an administrator exists, `/setup` and the bootstrap
  endpoint refuse. Set `ADMIN_PASSWORD` to create it server-side instead, for CI
  or an unattended deployment. See
  [ADR-0012](docs/adr/0012-first-run-in-the-browser.md).
- **`make upgrade`.** A self-hosted install is a checkout built from source, so
  upgrading is: fetch the newer release tag, check it out, rebuild.
  `scripts/upgrade.sh` checks GitHub for a newer release than your `VERSION`,
  shows what would change, and — once you confirm — does it, applying any new
  migrations through the `init` container. `ARGS=--check` only reports whether an
  update is available, which a cron entry or systemd timer can turn into a
  notification. It refuses to run over uncommitted changes, and configuration is
  untracked, so nothing you set is lost.
- **An update notification in the interface.** The gateway reports its running
  version at `GET /api/version` and, unless `UPDATE_CHECK` is off, checks the
  GitHub releases API — cached, sending nothing about the deployment — for a
  newer one. The interface shows a banner when one is out, pointing at the
  release notes and `make upgrade`. An air-gapped install sets
  `UPDATE_CHECK=false`.
- **Pull the images instead of building.** `make up` still builds the gateway
  and indexer from source; `make up ARGS=--pull` fetches the published images
  from GHCR instead — the path for a server without the disk or toolchain to
  build (a 25 GB VM ran out building from source). `REPO_MCP_TAG` chooses the tag
  (`dev-latest`, or a release), and `REPO_MCP_IMAGE` an internal mirror. The
  Compose services now carry both `image:` and `build:`.

### Changed

- **The whole documentation is on the site, built by Docusaurus.** It linked
  out to thirteen files on GitHub, which meant the site was an advertisement and
  the documentation lived somewhere else. `docs-site/` (Docusaurus) now builds
  every document under `docs/` — twelve documents and eleven decision records —
  with a sidebar, breadcrumbs, and links between the pages that resolve.

  The markdown stays the single source: `docs-site/scripts/sync-docs.mjs` copies
  it in on every build and rewrites the links that point outside `docs/` — a
  source file, `AGENTS.md`, `NOTICE` — to GitHub URLs, because there is no page
  for them here. A document missing from `docs-site/sidebars.js` fails the build
  rather than being published with no way to reach it. The reference
  documentation remains in English; the landing pages are Turkish and English.
- **The Turkish reads like Turkish.** The landing page and the primary README
  were written as a translation of the English — calqued sentence shapes, an
  archaic participle where an ordinary one belonged, headings that were not
  sentences. Both were rewritten, the use-case descriptions in particular.
- **Both READMEs are a landing page, not a manual.** The 699-line manual became
  a header — a row of badges and quick links — then what it is, why it matters,
  four commands to install, the interface in pictures, and links. Everything cut
  is on the site or in `docs/`, which is where it was already duplicated from.
- **`make setup` asks four questions, not five.** The fifth chose a repository
  provider; a connector — provider, organisation and an encrypted token — is
  created in the web interface now, so the wizard no longer asks and its intro
  says the questions pick which containers run, nothing more. `--provider` still
  writes a token variable for a scripted install that prefers one in
  `deploy/.env`.

### Fixed

- **`make setup` could put itself in a state it never recovered from.** On
  Debian and Ubuntu `venv` is a separate package, and without it
  `python3 -m venv` creates the directory and *then* fails for want of
  `ensurepip`. Setup tested `[[ -d .venv ]]`, so it took that wreckage for a
  finished environment and went straight to `./.venv/bin/pip: No such file or
  directory` — and every re-run did the same, because the directory was still
  there. Reported from a fresh Ubuntu server install.

  It now checks for `ensurepip` before doing any work and names the package to
  install; tests for the pip binary rather than the directory, so a half-made
  environment is rebuilt rather than trusted; checks the exit status of every
  `venv` and `pip` call, which none of them did; and warns when the interpreter
  is newer than the 3.13 CI tests against, since a dependency with no wheel for
  it fails during `pip` in a way that looks like a fault here.
- **`make setup` could not install gateway or indexer on a fresh server.** Both
  depend on `repo-mcp-common`, a sibling package whose local path is declared
  only in `[tool.uv.sources]` — a table `uv` reads and `pip` ignores. With each
  service in its own virtualenv, pip looked for `repo-mcp-common` on PyPI and
  failed with "No matching distribution found". Setup now installs the local
  `common` into the gateway and indexer venvs first, so the dependency is
  already satisfied when the service is installed.

  That surfaced a second wall on a VirtualBox shared folder, where `pwd` reports
  the tree as `//home/...`: the leading `//` broke both pip (read as a URL
  authority — "file:// scheme is supported only on localhost") and pytest (its
  summary's `relative_to()` raised, crashing a run whose tests had passed).
  `lib.sh` now collapses `REPO_ROOT` to a single leading slash, so every script
  agrees on the path. All reported from an Ubuntu server; none could occur in
  the sandbox.
- **A fresh install did not say how to reach the interface.** `make setup`
  finished with a list of dev scripts and no mention of the web UI, so it was
  unclear that nothing was running yet or how to open it once it was. The setup
  message and `deployment.md` now point at `http://localhost:8080/ui`, say
  `make up` starts containers rather than a system service, and note sign-in
  goes through OIDC. The workflow ran on
  pushes to `main`; GitHub creates the `github-pages` deployment environment
  with a branch policy that admits the default branch alone, and this
  repository's default branch is `dev`. A job whose environment refuses its ref
  does not fail with a message — it fails in one second having run no steps at
  all, so both runs looked like a build problem and were not one. The workflow
  now publishes from whichever branch is the default and skips visibly on any
  other, which needs no repository setting and survives the default branch
  being changed. Verified by dispatch: `deploy-pages` reported success and
  `https://emrezdemir.github.io/repo-mcp/` is live.
- **A documentation check had been passing without checking anything.**
  `check-docs.sh` verified that every document the README's index points at
  exists, by reading the section under `## Documentation` — and the day the
  primary README became Turkish that heading became `## Belgeler`, so the
  check matched nothing and reported success. It now reads both READMEs
  whole, accepts the site URLs they mostly use now, and fails if it matches
  implausibly few links, so the next time it goes hollow it says so.
- **An interface test had been red since the capability gate landed.**
  `NodeDetailPanel`'s "Show code" button is now behind `useCan`, and the test
  has no session, so the button it clicks was never rendered. The test asserts
  that fetched source is escaped rather than injected as HTML — worth keeping
  working — so it now mocks a caller whose role may read source.
- **Search answered from the screen rather than the project.** The graph is
  drawn up to a node budget, and the search box filtered only what was drawn
  — so a symbol that exists but was outside the budget produced "No matches".
  On a codebase large enough to need a budget, that is a wrong answer rather
  than a missing feature. Search now also asks `search_graph`, and anything
  found outside the drawn graph is listed separately with its location and
  source, saying plainly that its connections are not shown because they run
  to nodes that were not drawn.
- **The interface hid refusals.** A squad on the analysis profile cannot call
  `manage_adr` — correct — and the ADR dialog opened empty, the save did
  nothing and nothing said why. Refusals now appear in the platform's own
  words, which name what is missing. A save that silently does nothing is
  worse than one that fails.
- **`/api/session` under-reported what a caller may do.** It listed only the
  engine's tools, while `tools/list` also offers the composite ones when a
  model backend exists and the session can call the primitives they are built
  from — so the interface would have hidden Ask forever. Both now call
  `smart_tools_for`.
- **Selecting a symbol from the search results now opens its detail.** It used
  to highlight a dot somewhere in three dimensions and leave the person to
  find it, which made the source view effectively unreachable.
- **Escape closes the dialogs**, which also carry a dialog role and a label.
  By keyboard there had been no way out of them at all.
- Controls the platform would refuse are disabled with the reason on them
  rather than vanishing.

## [0.3.0] - 2026-08-02

### Changed

- **The web interface is the engine project's own, adopted rather than
  written here.** `graph-ui` — 60 files of React 19 and Three.js, MIT — is
  under `gateway/webui/` at a recorded upstream commit, and the ~2,500-line
  interface written for this repository is gone. Put side by side, upstream's
  is better, and it is separable from the 1,229 C files it ships beside.
  [ADR-0011](docs/adr/0011-adopt-the-upstream-interface.md) records the
  decision; ADR-0001 is unchanged — the engine is still wrapped, not forked.

  Adoption cost a URL and two headers, because the protocol was already the
  same: upstream posts JSON-RPC `tools/call` to `/rpc`, and the gateway
  accepts exactly that at `/mcp`. Everything the interface asks about a
  codebase therefore carries the caller's token and squad and goes through
  role capabilities, the project allowlist and the engine's tool profile.

- **The 3D layout is proxied, not reimplemented.** The engine computes it in
  C and serves it on a loopback port; the gateway starts each tenant's engine
  with that server on a port of its choosing and proxies `GET /api/layout`
  after authorizing the request exactly as it authorizes a tool call.
  Verified: the port refuses anything but loopback, an unauthenticated
  request gets 401, and another squad's project gets the platform's own
  refusal by name.

- **Everything else upstream reached for over HTTP is now a tool call**, and
  therefore behind a capability — project health and index status via
  `index_status`, ADRs via `manage_adr`, indexing via `index_repository`,
  deletion via `delete_project`, git metadata from `list_projects`.

### Removed

- **The filesystem browser, and the Control tab's process and log views.**
  They are meaningful on one machine and neither safe nor meaningful on a
  shared platform. The tab is the administrative console instead.
- `scripts/update-vendor.sh` and the three vendored UMD bundles, which
  belonged to the interface that is gone.

### Added

- **A Keycloak realm that ships.** `deploy/keycloak/repo-mcp-realm.json` is
  imported on first start: the groups the example squads refer to, a public
  browser client with PKCE for `/ui`, a confidential service client for CI,
  and the mappers that put the group list and the `repo-mcp` audience where
  the gateway looks for them. The directory was mounted and empty before, so
  the bundled identity provider started with nothing in it and the
  documentation was a list of console steps.

  It ships no users on purpose — the import runs with `OVERWRITE_EXISTING`, so
  a user in it would come back after every restart, and a repository that
  carries a working credential is a repository whose credential ends up in
  production. `scripts/keycloak-user.sh` creates one and prints a generated
  password once.

  Verified against a real Keycloak 26: realm imported, user created by the
  script, signed in through the browser, and the resulting token's `groups`
  and `aud` claims mapped to the expected role and squad. A user in
  `squad-checkout` correctly sees none of the payments squad's graph.

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
