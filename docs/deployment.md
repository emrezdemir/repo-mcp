# Deployment

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

`scripts/wizard.sh` asks five questions and writes the answer to
`deploy/.env` as a `COMPOSE_PROFILES` line. Compose reads that variable
itself, so `docker compose up` starts exactly those services afterwards.
`make setup` runs it on first install; `make wizard` re-runs it.

```bash
make wizard                          # ask, then rewrite deploy/.env

scripts/wizard.sh --force \
  --identity external --models external --provider github   # or say it directly

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
make up         # PostgreSQL, migrations, the first administrator, both services
```

The `init` container applies migrations and creates the first administrator
before either service starts. With `ADMIN_PASSWORD` empty in `deploy/.env` a
password is generated and printed once:

```bash
docker compose logs init
```

| Service | URL |
| --- | --- |
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

1. Create a realm (`engineering` in the example configuration).
2. Add **User federation → LDAP** with a read-only bind account. Set the
   users DN, the username attribute (`sAMAccountName` for Active Directory,
   `uid` for OpenLDAP) and enable periodic sync.
3. Add **Mappers → group-ldap-mapper** so directory groups become Keycloak
   groups.
4. Create a client `repo-mcp`, then add a **Group Membership** mapper with
   token claim name `groups` and *Full group path* switched **off** — the
   gateway strips a leading slash, but plain names keep the configuration
   readable.
5. Create a client scope so the `groups` claim is included in access tokens.
6. Theme the login page if you want the platform's own branding; it is still
   LDAP behind it.

For CI, create a service account client with client credentials and put it in
whichever groups grant the scope its pipelines need.

Verify a token before wiring agents up:

```bash
TOKEN=$(curl -s -d grant_type=password -d client_id=repo-mcp \
  -d username=alice -d password=... \
  http://localhost:8081/realms/engineering/protocol/openid-connect/token | jq -r .access_token)

curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'X-Tenant: payments' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq
```

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

## Kubernetes and more than one environment

The Helm chart deploys one environment. Configuration is not part of it —
squads, connectors, secrets and administrators are rows in that environment's
own database, entered once through the admin API.

```bash
cp deploy/helm/values-dev.example.yaml values-dev.yaml
helm upgrade --install repo-mcp deploy/helm/repo-mcp \
  -n repo-mcp-dev --create-namespace -f values-dev.yaml
```

Two things the chart refuses rather than warns about, because both fail
silently and late: a mutable image tag when `environment: production`, and
`migrations.auto` in production. The full list, the promotion flow from `dev`
to a version tag, and how to roll back are in
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
