# Environments and promotion

`main` and `dev` are a code lifecycle. They are not environments. This page
describes how code on a branch becomes something running somewhere, and what
each environment owns for itself.

The reasoning behind all of it is in
[ADR-0008](adr/0008-environments-and-promotion.md); this is the operational
version.

## The shape of it

```
feature/*  ──PR──▶  dev  ──CI──▶  :dev-<sha>   ──deploy──▶  dev environment
                     │             :dev-latest              own DB, own SECRETS_KEY
                     │
                     └─merge──▶  main  ──tag v0.2.0──▶  :v0.2.0    ──promote──▶  production
                                                         :sha-<sha>              own DB, own SECRETS_KEY
```

Three rules follow from it, and everything else on this page is a consequence:

1. **Branches produce artifacts.** CI builds an image, tests it, and pushes it.
2. **Artifacts are promoted.** Production runs a tag that already ran in dev.
   Nothing is rebuilt on the way.
3. **Configuration is never promoted.** Squads, connectors, secrets and
   administrators are environment state, and each environment has its own.

## What each environment owns

| | dev | production |
| --- | --- | --- |
| Image tag | `dev-latest` or `dev-<sha>` | `v0.2.0` or `sha-<commit>` |
| Database | its own | its own |
| `SECRETS_KEY` | its own | its own |
| Administrators | its own | its own |
| Squads and connectors | test organisations | the real ones |
| Migrations | automatic (`migrations.auto: true`) | a deliberate step |
| Helm values | `values-dev.yaml`, untracked | `values-production.yaml`, untracked |

Nothing in that table is shared. A shared `SECRETS_KEY` in particular would
mean anyone with dev access can decrypt production credentials, which quietly
undoes the reason credentials are encrypted at all.

## Deploying dev

```bash
cp deploy/helm/values-dev.example.yaml values-dev.yaml
# fill in database.url and secretsKey (repo-mcp-admin generate-key)

helm upgrade --install repo-mcp deploy/helm/repo-mcp \
  -n repo-mcp-dev --create-namespace \
  -f values-dev.yaml
```

`migrations.auto: true` runs the schema as a pre-install/pre-upgrade hook and
creates the first administrator if none exists. Read its generated password
once:

```bash
kubectl -n repo-mcp-dev logs job/repo-mcp-bootstrap
```

Then configure the environment — squads, roles, connectors, the OIDC issuer —
through the admin API or `repo-mcp-admin import`. See
[deployment.md](deployment.md).

## Cutting a release

```bash
git checkout main && git pull origin main
git merge --no-ff dev

scripts/version.sh --bump minor        # VERSION, three packages, the chart
# move CHANGELOG.md's [Unreleased] entries under ## 0.2.0
# update both READMEs: the version line, and anything the release changed
make screenshots                       # if the output in them moved
make verify

git commit -am "release 0.2.0"
git push origin main

git tag -a v0.2.0 -m "0.2.0"
git push origin v0.2.0
```

`VERSION` is the single authoritative number; `scripts/version.sh` propagates
it to the three Python packages and the chart, and `--check` — part of
`make verify` — fails when any of them, or either README, disagrees. Five
copies kept in step by hand is five chances to ship a chart that deploys an
image it does not match.

The tag is the promotion event. `.github/workflows/release.yml` refuses it
unless the commit is on `main`, `VERSION` agrees with the tag, everything
agrees with `VERSION`, and `CHANGELOG.md` has a section for it — all trivial
to fix before a release and awkward to fix after one.

## Deploying production

```bash
helm upgrade --install repo-mcp deploy/helm/repo-mcp \
  -n repo-mcp \
  -f values-production.yaml \
  --set image.tag=v0.2.0
```

Migrations are not automatic here. Apply the schema as its own step, confirm
it, then deploy:

```bash
kubectl -n repo-mcp run repo-mcp-migrate --rm -i --restart=Never \
  --image=ghcr.io/emrezdemir/repo-mcp-gateway:v0.2.0 \
  --env=MIGRATE_ON_START=true \
  --env=DATABASE_URL=... --env=SECRETS_KEY=... \
  --command -- repo-mcp-admin init-db
```

Rolling back is redeploying the previous tag:

```bash
helm upgrade repo-mcp deploy/helm/repo-mcp -f values-production.yaml \
  --set image.tag=v0.1.0
```

A migration is not rolled back by that. If a release includes one that is not
backwards compatible, say so in the changelog — the rollback then needs a
plan, and the release notes are where someone will look for it.

## What the chart refuses

Each of these renders something that looks fine and behaves badly later, so
the chart fails at template time rather than warning:

| Refused | Why |
| --- | --- |
| `environment: production` with tag `latest`, `dev`, `dev-latest`, `main` or `edge` | "Which commit is running" becomes unanswerable, and a rollback becomes a rebuild |
| `environment: production` with `migrations.auto: true` | A schema change should be a decision, not a side effect of a deploy |
| No `database.url` and no `secrets.existingSecret` | There is no configuration to read; every request would fail with a message about something else |
| No `secretsKey` and no `secrets.existingSecret` | Provider tokens cannot be decrypted, and a generated-per-boot key looks like data loss |
| `gateway.autoscaling` without `ReadWriteMany` | Replicas answer from an empty graph — [scaling.md](scaling.md) |

`scripts/check-chart.sh` catches the complementary mistake, which Helm cannot:
a template reading a `.Values` path that no longer exists renders as an empty
string rather than an error.

## Migrations

`MIGRATE_ON_START` decides whether a starting process may apply the schema. It
defaults to **false** — the safe answer for the environment nobody is
watching.

| Where | Value | Set by |
| --- | --- | --- |
| Compose stack | true | `deploy/docker-compose.yml` |
| `scripts/dev.sh` | true | the script |
| dev cluster | true, in the hook Job only | `migrations.auto: true` |
| production | false | the default, and the chart refuses otherwise |

Auto-migration is convenient exactly until the first migration that takes a
table lock, or the first time an older replica starts against a newer schema
during a rollback. Dev keeps the convenience because that is where the
discovery should happen.

## Local development

`scripts/dev.sh` creates a SQLite database under `.dev/`, applies the schema,
seeds it from `deploy/tenants.yaml` and `deploy/scan.yaml`, and creates a
local administrator. It is a single-machine convenience: SQLite is supported
for development and for the tests, and nothing else. Anything shared uses
PostgreSQL.

`scripts/stack.sh up` brings up the Compose stack, which uses the bundled
PostgreSQL and is the closest local thing to a real environment.

## Adding another environment

Staging, or a second production region, is a values file and a database — not
a branch. Deliberately: a third long-lived branch is a thing to keep merged,
solving a problem tags already solve.

```bash
cp deploy/helm/values-production.example.yaml values-staging.yaml
# environment: staging, its own database.url, its own secret, its own hostname
```

`deploy/helm/values-*.yaml` is untracked, and `values-*.example.yaml` is the
tracked reference. That is the same rule as `deploy/.env` and
`deploy/tenants.yaml`, for the same reason: environment-specific values on a
long-lived branch are what make `main` and `dev` conflict on every merge —
see [branching.md](branching.md).
