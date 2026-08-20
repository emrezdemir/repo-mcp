# Deployment

## Requirements

Linux or macOS, with Docker 24+ or Podman 4.1+. Everything else depends on
whether you **build** the images or **pull** them, and whether you run the
bundled model backend (LiteLLM + Ollama).

**Supported platforms.** Linux and macOS, on **x86-64 (amd64)** and **ARM64** —
including Apple Silicon and ARM servers such as Graviton. The published images
carry both architectures, so `make up ARGS=--pull` gets a native image either
way. Windows is not supported and there is no plan for it.

The architectures are not cosmetic: an image of the wrong one **does not work**
here, and it fails in a way that looks like a hang rather than an error. The
container starts, a shell in it runs — and the engine binary then blocks
forever under emulation, which is the one thing the image exists to carry. That
is why both the release workflow and CI publish a manifest with both, and why
the release asserts both are present rather than assuming the build honoured
the list.

macOS is a first-class *development* host (see [development.md](development.md))
and will run the stack, but a deployment still belongs on Linux — that is where
the memory limits, the storage topology and the Helm chart are aimed.

| Setup | CPU | RAM | Free disk |
| --- | --- | --- | --- |
| Evaluate — pull images, external or no model backend | 2 cores | 4 GB | ~15 GB |
| Real indexing — pull images, external models | 4 cores | 8–16 GB | ~20 GB + your repos |
| Build the images from source | — | — | **+15 GB during the build** |
| Bundled models (LiteLLM + Ollama) | +2 cores | **+16 GB** | + the model size (several GB) |

**Building from source is the disk-heavy part.** The web interface's npm build,
the engine and both services produce several GB of layers, and a small VM runs
out with **`no space left on device`** — which is what a 25 GB VirtualBox disk
does. Either give the machine a larger disk, or **pull the images**
(`make up ARGS=--pull`) so nothing is built on the server at all; the images are
a fraction of the build's footprint.

Indexing is RAM-first: the indexer loads a repository's graph into memory and
releases it afterwards, so peak RAM tracks the largest repository, not the total.
The graph stores on disk grow with everything you index — budget for that beyond
the numbers above.

## Which path

| You want to… | Run |
| --- | --- |
| Try it on your machine — and maybe develop or run the tests | `make setup`, then `make up` |
| Run it on a server, only the stack | `make setup ARGS=--config-only`, then `make up` |
| Run it on Kubernetes | The Helm chart — see [Kubernetes](#kubernetes) |
| Change which optional components run, later | `make wizard` |

`make setup` and `make setup ARGS=--config-only` produce the **same running
stack** — `make up` starts the same containers either way. The only difference is
whether `make setup` also builds the three Python virtualenvs, which `make test`
and `make dev` (running the services without Docker) need; a server that only
runs `make up` does not, and `--config-only` installs no Python at all.
`make wizard` is just the four-question component choice from setup, re-runnable
on its own to change which optional containers run.

The stack is **built from source** on the first `make up` — the web interface,
the engine and both services — which needs a few GB of free disk for the build
layers. On a small VM the build can fail with **`no space left on device`**;
reclaim space with `podman system prune -af` (or `docker system prune -af`), or
give the machine a larger disk. `df -h` shows what is left.

## Configuration lives in PostgreSQL

Tenants, roles, connectors, OIDC and LiteLLM settings, tunables and provider
tokens are all rows in a database, changed through the admin API while the
platform runs. Only what is needed *before* the database can be read stays in
the environment. See [ADR-0006](adr/0006-configuration-in-the-database.md).

| Environment | Database |
| --- | --- |
| `DATABASE_URL`, `SECRETS_KEY` | tenants, roles, project allowlists |
| `CBM_*` paths and the engine binary | connectors and provider tokens |
| `PORT`, `WEB_CONCURRENCY`, log level | OIDC and LiteLLM settings, tunables |

## Choosing which components run

Four services are optional: Keycloak, LiteLLM, Ollama and headroom. They are
Compose profiles rather than a second compose file — separate files would
duplicate the four services that are not optional, and the two copies would
drift.

`scripts/wizard.sh` asks four questions — which of the optional components to
run — and writes the answer to `deploy/.env` as a `COMPOSE_PROFILES` line.
Compose reads that variable itself, so `docker compose up` starts exactly those
services afterwards. `make setup` runs it on first install; `make wizard`
re-runs it.

```bash
make wizard                          # ask, then rewrite deploy/.env

scripts/wizard.sh --force \
  --identity external --models external   # or say it directly

scripts/wizard.sh --show             # what is currently selected
```

| Answer | Profiles added | What it means |
| --- | --- | --- |
| `--identity keycloak` | `keycloak` | Keycloak runs on :8081, federated from LDAP |
| `--identity external` | none | Point `oidc.issuer` at your own provider |
| `--identity dev` | none | JWT verification off, a static token — evaluation only |
| `--models bundled` | `litellm ollama` | LiteLLM on :4000 in front of a local Ollama |
| `--models external` | none | Point `litellm.base_url` at your own proxy |
| `--models none` | none | The two composite tools stay unavailable |
| `--compression on` | `headroom` | Deployed, still off until `headroom.enabled` is set |
| `--database external` | none | Writes `DATABASE_URL` instead of using the bundled PostgreSQL |

Without a terminal the wizard asks nothing and writes the full bundled stack,
so `make setup` still works inside a script.

Two secrets — `KEYCLOAK_ADMIN_PASSWORD` and `LITELLM_MASTER_KEY` — are always
written even when their profile is off. Compose interpolates every service
definition regardless of profile, so a missing one would break the whole file;
writing them also means turning a profile on later needs no other edit.

## Local evaluation

```bash
make setup      # generates POSTGRES_PASSWORD, SECRETS_KEY and the rest
make up         # PostgreSQL, migrations, both services
```

`make setup` only prepares: it writes `deploy/.env`, the two seed YAML files and
the secrets, and — unless `--config-only` — the virtualenvs. Nothing is running
yet, and there is no system service to install. `make up` starts the Docker
containers; `make down` stops them. Once it is up, the **web interface is at
http://localhost:8080/ui** — from another machine, replace `localhost` with the
server's address and open port 8080.

On first open there is no administrator yet, so the interface shows a one-time
setup screen: choose a username and password, and it creates the first
administrator. From there you configure the platform — squads, connectors,
secrets — and point it at your identity provider so everyone else signs in
through it (see [Keycloak and LDAP](#keycloak-and-ldap)). `make debug` reports
what is up and what is not.

To create the administrator without a browser — in CI, or an unattended
deployment — set `ADMIN_PASSWORD` in `deploy/.env` before `make up` and the
`init` container creates it instead. See
[ADR-0012](adr/0012-first-run-in-the-browser.md).

### Docker or Podman

Either works. The scripts detect which is installed — Docker is preferred,
Podman is the fallback — so `make up`, `make down`, `make build` and the rest run
on whichever is present. Force one with `CONTAINER_ENGINE`:

```bash
CONTAINER_ENGINE=podman make up
```

Podman needs a compose implementation: `podman compose` (Podman 4.1+) or
`podman-compose`. Rootless Podman is fine here — every published port is above
1024 (8080, 8081, 8082, 4000, 5432), so nothing needs privilege.

### On a server, where you only want the stack

`make setup` also builds three virtualenvs, because that is what running the
tests and `make dev` needs. A machine that will only ever run `make up` needs
none of them — the stack is entirely containers — and on a fresh Debian or
Ubuntu it would have to install a Python toolchain first, since `venv` ships
as its own package there.

```bash
make setup ARGS=--config-only    # writes deploy/.env and the two YAML files
make up
```

It skips the dependencies and the configuration check that needs them; the
services validate their own configuration at startup, so a mistake surfaces
when `make up` fails rather than silently. Run plain `make setup` on a machine
where you also intend to develop.

### Build from source, or pull the images

`make up` builds the gateway and indexer images from this checkout, which needs
build tools and a few GB of free disk — a small VM can run out. A server that
would rather not build can pull the published images instead:

```bash
make up ARGS=--pull    # pull ghcr.io/emrezdemir/repo-mcp-*, then start
```

Choose the tag with `REPO_MCP_TAG` in `deploy/.env` — `dev-latest` for the latest
dev build, `v0.4.0` for a release — and set `REPO_MCP_IMAGE` to an internal
mirror if you keep one. A private GHCR package needs a login first:
`podman login ghcr.io` (or `docker login`). CI publishes `:dev-latest` and
`:dev-<sha>` from `dev`; a release publishes `:vX.Y.Z` and `:latest`.

The `init` container applies migrations before either service starts, and — when
`ADMIN_PASSWORD` is set — creates the first administrator. With it empty (the
default) the administrator is created in the browser on first open instead
(above). `init` runs once and exits; `docker compose logs init` shows what it
did.

| Service | URL |
| --- | --- |
| Web interface | http://localhost:8080/ui |
| Gateway (MCP) | http://localhost:8080/mcp |
| Gateway (admin API) | http://localhost:8080/admin |
| Indexer | http://localhost:8082 |
| Keycloak | http://localhost:8081 |
| LiteLLM | http://localhost:4000 |
| PostgreSQL | localhost:5432 |

A freshly bootstrapped platform has no squads, and `/readyz` says so rather
than looking healthy:

```json
{"status": "ok", "tenants": [], "warning": "no squads are configured; ..."}
```

## Upgrading

`scripts/upgrade.sh` (or `make upgrade`) checks GitHub for a newer release and,
if there is one, upgrades this install to it:

```bash
make upgrade                 # check, show what changed, ask, then rebuild
make upgrade ARGS=--check    # only report whether an update is available
```

It compares the latest release to your `VERSION` and, once you confirm, fetches
the tag, checks it out and runs `make up` — which rebuilds the images and applies
any new migrations through the `init` container. Configuration in `deploy/.env`
and the database is untracked, so nothing you set is touched, and it refuses to
run with uncommitted changes in the checkout.

The interface shows a banner when a newer release is out: the gateway checks the
GitHub releases API (cached, and sending nothing about the deployment), which
`UPDATE_CHECK=false` turns off for an air-gapped install. A cron entry or a
systemd timer running `make upgrade ARGS=--check` is the headless equivalent.
The upgrade itself always stays a deliberate, confirmed step.

On Kubernetes the upgrade is a chart or image-tag bump instead — see
[environments.md](environments.md).

## Bringing your own PostgreSQL

Set `DATABASE_URL` and skip the bundled container:

```bash
# deploy/.env
DATABASE_URL=postgresql+asyncpg://repomcp:password@db.internal:5432/repomcp

docker compose up -d --scale postgres=0
```

Nothing else changes: same schema, same migrations, same commands. A plain
`postgresql://` URL is rewritten to the async driver automatically.

Requirements: PostgreSQL 14 or newer and a role that may create tables in its
own schema. At startup the services retry for
`DATABASE_CONNECT_RETRY_SECONDS` (60 by default) rather than crash-looping
while the database comes up.

## Configuring the platform

Through the admin API:

```bash
TOKEN=$(curl -s -X POST localhost:8080/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}' | jq -r .token)

curl -X PUT localhost:8080/admin/tenants/payments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ldap_groups":["squad-payments"],"projects":["acme-payments-*"],"tool_profile":"analysis"}'

curl -X PUT localhost:8080/admin/secrets/github.token \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":"ghp_...","description":"acme org"}'

curl -X PUT localhost:8080/admin/connectors/acme-github \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"provider":"github","tenant":"payments","settings":{"org":"acme"},"token_secret":"github.token"}'
```

Or by importing YAML, which is the migration path from an older deployment:

```bash
docker compose run --rm init repo-mcp-admin import \
  --tenants /etc/repo-mcp/tenants.yaml --scan /etc/repo-mcp/scan.yaml
```

The import copies token values out of the environment into encrypted storage,
turning a `token_env` reference into a stored secret. It is idempotent.

Changes reach every replica within `CONFIG_POLL_SECONDS` (15 by default), with
no restart, and each one is recorded with an actor in `/admin/audit`.

Trigger the first discovery pass:

```bash
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

## The administrator account

A local account exists so the platform can be configured before the identity
provider is — including configuring the identity provider itself. It reaches
the admin API only: it cannot call MCP tools, query a graph or read source.
See [ADR-0007](adr/0007-break-glass-administrator.md).

```bash
docker compose run --rm init repo-mcp-admin create-admin --username alice
docker compose run --rm init repo-mcp-admin set-password admin
docker compose run --rm init repo-mcp-admin status
```

**The generated bootstrap password is printed once**, to the `init`
container's log. A log aggregator will have captured it; rotate it with
`set-password` after the first login if that matters to you.

## SECRETS_KEY

Provider tokens are encrypted at rest with it. It must be stable across
restarts and identical on every replica — losing it means re-entering every
credential, and the failure names the key rather than looking like data
corruption.

```bash
make generate-key
```

Back it up somewhere other than the database it protects.

## Keycloak and LDAP

### The bundled realm

`deploy/keycloak/repo-mcp-realm.json` is imported on first start of the
bundled Keycloak. It carries:

| | |
| --- | --- |
| Groups | the nine that `deploy/tenants.example.yaml` refers to |
| `repo-mcp-web` | the browser client for `/ui`: public, PKCE `S256`, redirecting to `http://localhost:8080/ui` |
| `repo-mcp-agent` | a confidential client with a service account, for CI and headless agents |
| Mappers | on both clients: `groups` as a plain-name claim, and `repo-mcp` added to the token audience |

It carries **no users**. A repository that ships a working credential is a
repository whose credential ends up in production, and the realm is imported
with `OVERWRITE_EXISTING` — a user in it would come back after every restart.

To create one:

```bash
scripts/keycloak-user.sh ada --name "Ada Lovelace" --group squad-payments
```

The password is generated and printed once unless `--password` is given.
`--group` is repeatable and required: a user in no group has neither a role
nor a squad, and every request from them would be refused.

Then point the interface at it:

```bash
repo-mcp-admin set oidc.issuer http://localhost:8081/realms/repo-mcp
repo-mcp-admin set oidc.browser_client_id repo-mcp-web
```

For a different hostname, change the client's **Valid redirect URIs** and
**Web origins** to match. Web origins is the one people miss: without it the
browser's request to the token endpoint is refused by CORS, and the sign-in
fails *after* the redirect rather than before it.

### Federating a real directory

The bundled realm is a starting point. For a real deployment:

1. Add **User federation → LDAP** with a read-only bind account. Set the users
   DN, the username attribute (`sAMAccountName` for Active Directory, `uid`
   for OpenLDAP) and enable periodic sync.
2. Add **Mappers → group-ldap-mapper** so directory groups become Keycloak
   groups. The names have to match the `ldap_groups` in your squads.
3. Leave the group membership mapper's *Full group path* switched **off** —
   the gateway strips a leading slash either way, but plain names keep the
   configuration readable.
4. Theme the login page if you want the platform's own branding; it is still
   the directory behind it.

An external Keycloak, or another provider entirely, needs the same three
things: a `groups` claim, `repo-mcp` in the audience, and a public client with
PKCE if the web interface is to be used.

### Verifying a token

```bash
TOKEN=$(curl -s -d grant_type=client_credentials \
  -d client_id=repo-mcp-agent -d client_secret=... \
  http://localhost:8081/realms/repo-mcp/protocol/openid-connect/token | jq -r .access_token)

curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'X-Tenant: payments' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq
```

The service client's secret is in the Keycloak console under **Clients →
repo-mcp-agent → Credentials**; it is generated on import rather than shipped.
Put the service account in whichever groups grant the scope its pipelines
need — **Service account roles → Groups** on that client.

## Webhooks

Point each repository or organisation at the indexer:

| Provider | URL | Secret header |
| --- | --- | --- |
| GitHub | `POST /webhook/github` | `X-Hub-Signature-256`, secret in `WEBHOOK_SECRET_GITHUB` |
| GitLab | `POST /webhook/gitlab` | `X-Gitlab-Token`, secret in `WEBHOOK_SECRET_GITLAB` |
| Bitbucket | `POST /webhook/bitbucket` | `X-Hub-Signature`, secret in `WEBHOOK_SECRET_BITBUCKET` |

Only push events on the default branch are indexed centrally. Branch
deletions and pushes to other refs are acknowledged and ignored.

## CI integration

```yaml
- name: Refresh the code graph
  run: |
    curl -fsS -X POST "$REPO_MCP_INDEXER/trigger" \
      -H "Authorization: Bearer $CI_TRIGGER_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "{\"repository\": \"$GITHUB_REPOSITORY\", \"sha\": \"$GITHUB_SHA\"}"
```

## The answer cache

Off by default. It stores `ask_codebase` answers per squad, so a repeated
question costs one row read instead of thousands of tokens, and it is keyed on
the project's index epoch — a reindex retires every answer computed from the
previous graph.

```bash
repo-mcp-admin set answer_cache.enabled true
# Optional. Without it, only exact repeats hit; with it, close questions do too.
repo-mcp-admin set answer_cache.embedding_model text-embedding-3-small
repo-mcp-admin set answer_cache.similarity_threshold 0.95
repo-mcp-admin set answer_cache.ttl_seconds 604800
```

The threshold is high on purpose: a miss costs tokens and seconds, while a
false hit is fluent, plausible, about a different question and very hard to
notice. Lower it deliberately, watching
`repo_mcp_answer_cache_lookups_total`.

Two things to weigh before enabling it. Cached answers contain synthesised
knowledge of a squad's source, so the database now holds more than
configuration — the squad boundary applies to every lookup, but the blast
radius of a database disclosure is larger. And the embedding model is called
with the question text through the same LiteLLM proxy, with the squad's own
key. `DELETE /admin/answer-cache` clears it; setting `answer_cache.enabled`
to false stops it.

Why there is no vector database here, and when there should be, is in
[ADR-0009](adr/0009-answer-cache.md).

## Prompt compression

Optional, off by default. [Headroom](https://github.com/headroomlabs-ai/headroom)
sits between the gateway and LiteLLM and compresses the evidence sent to the
model — mostly JSON, which is what it is best at. It is upstream software run
from its own pinned image: this repository deploys it and contains none of it,
so updating it is bumping a tag.

```bash
# Compose: its own profile, so the default stack is unchanged.
docker compose --profile headroom up -d

# Kubernetes: headroom.enabled=true, with a pinned tag. The chart refuses an
# unpinned one — a proxy that changes underneath you changes what the model is
# told, silently.
```

Headroom forwards to a model proxy, and `HEADROOM_UPSTREAM_URL` in `deploy/.env`
is which one. With the bundled LiteLLM that is `http://litellm:4000/v1`, and
`make setup` writes it. With your own proxy the wizard asks for the URL, because
the container name resolves to nothing outside the stack — a wrong value here
does not fail at `make up`, it fails on the first request that reaches the
model.

Deploying it is not the same as using it. Point the platform at it and turn it
on, which is also how it is turned off:

```bash
repo-mcp-admin set headroom.base_url http://headroom:8787/v1
repo-mcp-admin set headroom.enabled true
```

Two properties are worth knowing before enabling it. If it is unreachable, the
gateway answers through LiteLLM directly and logs it —
`repo_mcp_compression_fallbacks_total` counts that, and
`headroom.fallback_to_litellm` turns the behaviour off for an operator who
wants compression or nothing. And embeddings never go through it: compressing
the text would move the vector the answer cache keys on.

Raw engine output — `get_code_snippet` included — never reaches it either, and
not by policy: tool results are returned to the client without passing through
a model at all, so there is no path from them to a compression proxy.

The reasoning, and what compression can cost you, is in
[ADR-0010](adr/0010-headroom-plugin.md).

## Kubernetes

The Helm chart in `deploy/helm/repo-mcp` deploys one environment: the gateway,
the indexer, their storage, and — optionally — an ingress, an HPA, a
PodDisruptionBudget, a NetworkPolicy and a ServiceMonitor. Configuration is not
part of it: squads, connectors, secrets and settings are rows in that
environment's database, entered once the platform is up.

### Before you install

- A **Secret** carrying `DATABASE_URL` and `SECRETS_KEY` — the chart reads both
  from a Secret you manage rather than from values, so neither ends up in a file:

  ```bash
  kubectl create namespace repo-mcp
  kubectl -n repo-mcp create secret generic repo-mcp-production \
    --from-literal=DATABASE_URL='postgresql+asyncpg://repomcp:PW@db:5432/repomcp' \
    --from-literal=SECRETS_KEY="$(make generate-key)"
  ```

- A **PostgreSQL** the pods can reach (the chart runs none — production data does
  not belong in a pod's ephemeral storage). PostgreSQL 14 or newer.
- A **storage class** that handles SQLite WAL locking: a block volume, never NFS
  (see [scaling.md](scaling.md)).

### Install

```bash
cp deploy/helm/values-production.example.yaml values-production.yaml
# edit at least: image.tag (an immutable tag), the ingress host, storageClass
helm upgrade --install repo-mcp deploy/helm/repo-mcp \
  -n repo-mcp -f values-production.yaml
```

Production refuses two things at template time rather than warning, because both
fail silently and late: a mutable image tag (`latest`, `dev`, `main`), and
`migrations.auto: true`. Apply the schema as its own deliberate step first:

```bash
kubectl -n repo-mcp run repo-mcp-migrate --rm -i --restart=Never \
  --image=ghcr.io/emrezdemir/repo-mcp-gateway:v0.4.0 \
  --env=MIGRATE_ON_START=true --env=DATABASE_URL=... --env=SECRETS_KEY=... \
  --command -- repo-mcp-admin init-db
```

### Reach the interface and create the administrator

The example ingress routes `/mcp` to the gateway and `/webhook` to the indexer.
**To use the web interface, add the gateway's UI paths** — `/ui`, `/setup`,
`/api` and `/admin` — or route `/` to the gateway. Then open `https://<host>/ui`:
with no administrator yet it shows the one-time first-run screen
([ADR-0012](adr/0012-first-run-in-the-browser.md)). To create the administrator
without a browser instead, put `ADMIN_PASSWORD` in the Secret and the bootstrap
job creates it.

Without an ingress, port-forward:

```bash
kubectl -n repo-mcp port-forward svc/repo-mcp-gateway 8080:8080
# then open http://localhost:8080/ui
```

### Scaling, and upgrading

The indexer stays at one replica — its queue and locks are in-process
([scaling.md](scaling.md)). The gateway scales out only with `ReadWriteMany`
storage and read-only tool profiles, a combination the chart enforces rather
than lets you get half right. Upgrading is a new immutable tag:

```bash
helm upgrade repo-mcp deploy/helm/repo-mcp -n repo-mcp \
  -f values-production.yaml --set image.tag=v0.5.0
```

The promotion flow from `dev` to a version tag, and how to roll back, are in
[environments.md](environments.md).

## Production notes

**One pinned engine build.** The engine enforces an exact-build admission barrier
across processes sharing a cache root. Pin `CBM_VERSION` in the image and
upgrade a tenant's processes together — `Recreate`, not `RollingUpdate`. A
half-upgraded tenant fails with a version cohort conflict.

**Build the engine in from your own infrastructure.** The image fetches the
engine at build time: a `.tar.gz` per OS and architecture, alongside a
`checksums.txt` covering every asset. The build verifies against that file
automatically, so nothing has to be copied by hand.

For an air-gapped or supply-chain-controlled build, mirror the release —
archives and `checksums.txt` — and point the build at it:

```bash
docker build -f deploy/Dockerfile \
  --build-arg SERVICE=gateway \
  --build-arg CBM_RELEASE_BASE=https://artifacts.internal/repo-mcp/engine \
  --build-arg CBM_VERSION=v0.9.0 \
  .
```

| Build argument | Use it for |
| --- | --- |
| `CBM_VERSION` | A pinned release tag. Pin it in production — every engine process sharing a cache root must be the same build |
| `CBM_RELEASE_BASE` | An internal mirror laid out like the upstream releases |
| `CBM_DOWNLOAD_URL` | A single archive URL, when your mirror names files differently |
| `CBM_SHA256` | The archive's checksum, when your mirror publishes no `checksums.txt` |
| `CBM_VARIANT` | Defaults to `-portable`, the statically linked build. Set it to empty for the glibc build only if your base image has GLIBC 2.38 or newer — Debian bookworm does not, and the glibc build downloads fine and then fails on its first run |

A mirror that publishes neither `checksums.txt` nor a `CBM_SHA256` still
builds, and says so on the build log — an unverified download is a decision,
not a silent default.

**Never expose the engine.** The engine has no authentication. The gateway is the only
ingress; `CBM_ALLOWED_ROOT` is the backstop, not the control.

**Storage.** Stores are plain files at `<cache>/tenant/<squad>/<project>.db`,
so back-up and tenant migration are file copies. Use a filesystem that handles
SQLite WAL correctly — local disk or a block volume, not NFS.

**Resource limits.** Set `CBM_WORKERS` and `CBM_MEM_BUDGET_MB` to match pod
limits. Indexing is RAM-first and releases memory afterwards, so the peak is
what matters for sizing.

**Sizing the first run.** Indexing an entire organisation the first time is the
expensive moment; steady-state incremental runs are far cheaper. Start one
connector with `mode: fast`, measure, then widen.

**Secrets.** Provider tokens and LiteLLM keys are stored encrypted in the
database and entered through the admin API; only `DATABASE_URL`, `SECRETS_KEY`
and the webhook and CI secrets come from the environment. `tenants.yaml` and
`scan.yaml` are seed documents for `repo-mcp-admin import` — they are meant to
be readable in review, and they carry no token values.

**One environment, one key.** Each environment has its own database, its own
`SECRETS_KEY` and its own administrators. Sharing a key between dev and
production would let anyone with dev access decrypt production credentials.
