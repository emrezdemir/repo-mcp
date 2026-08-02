# ADR-0008: Environments are separated by artifact and database, not by branch

- **Status:** Accepted
- **Context:** `main` and `dev` exist, but nothing said how either reaches a
  running environment. Moving configuration into a database
  ([ADR-0006](0006-configuration-in-the-database.md)) made the question urgent.

## Context

`main` and `dev` are a **code lifecycle**: integration and stable. That is not
the same thing as a dev environment and a production environment, and treating
one as the other is how organisations end up with "prod is whatever `main`
built last Tuesday".

Three gaps made this concrete:

1. **No artifact.** CI built images and discarded them (`load: true`, tag
   `:ci`). Promoting `dev` to `main` moved *source*, and production then built
   its own image — so what ran in production was never the thing that was
   tested.
2. **No environment configuration.** One `values.yaml` with defaults, and
   nothing describing how a second environment differs.
3. **Migrations ran on every start.** The `init` container calls
   `repo-mcp-admin init` unconditionally. Point a `dev`-branch build at the
   production database and unreleased migrations run against production, with
   nobody deciding that.

Configuration living in a database adds a dimension the file-based version did
not have: each environment now has its own tenants, connectors, secrets and
administrators, as rows.

## Decision

**Branches produce artifacts. Artifacts are promoted to environments.
Configuration is never promoted.**

```
feature/* ──PR──▶ dev ──build──▶ :dev-<sha> ──deploy──▶ dev environment
                   │                                    (own DB, own SECRETS_KEY)
                   └─merge──▶ main ──tag──▶ :vX.Y.Z ──promote──▶ production
                                                       (the same image, not rebuilt)
```

**1. Immutable, promotable images.** CI pushes `:dev-<sha>` from `dev` and
`:vX.Y.Z` plus `:sha-<sha>` from a version tag. Production runs a version tag
that already ran in the dev environment. Nothing rebuilds for production.

**2. `latest` is refused in production.** The chart fails to render when
`environment: production` and the image tag is `latest` or empty. A mutable
tag makes "what is running" unanswerable at exactly the moment it matters.

**3. Every environment owns its state.** Its own database, its own
`SECRETS_KEY`, its own administrators, its own tenants and connectors. Sharing
a `SECRETS_KEY` between environments would let anyone with dev access decrypt
production credentials.

**4. Configuration is environment state, not code.** There is no promotion
path for a tenant or a connector, deliberately. `repo-mcp-admin import` seeds
an environment; it does not synchronise two.

**5. Migrations are automatic in dev and deliberate in production.**
`MIGRATE_ON_START` defaults to true in the Compose stack and **false** in the
chart. Production upgrades run the migration as an explicit step — a Helm
pre-upgrade hook when `migrations.auto` is set, or a command someone runs.

## Rationale

**Why not "the branch is the environment".** It reads well on a diagram and
fails in practice: a hotfix has to reach production without dragging along
whatever else is on the branch, and a rollback becomes a revert commit and a
rebuild instead of redeploying the previous tag. Artifacts make both trivial.

**Why refuse `latest` rather than warn.** The same reasoning as the chart's
existing refusal to autoscale without shared storage
([ADR-0005](0005-storage-topology.md)): the failure is silent and shows up
later as an inexplicable difference between two pods. Failing at template time
costs a minute.

**Why migrations are not automatic in production.** Auto-migration is
convenient exactly until the first migration that takes a table lock, or the
first time an older replica starts against a newer schema during a rollback.
Neither should be discovered in production. Dev keeps the convenience because
that is where the discovery should happen.

**Why configuration is not promoted.** It is not the same *kind* of thing as
code. Dev has test squads pointed at test organisations; production has real
ones. Copying between them would either overwrite real state or require a
merge strategy for rows, which is a database replication problem nobody asked
for.

## Consequences

**Positive**

- What runs in production is byte-identical to what was tested.
- Rollback is redeploying the previous tag.
- A dev-branch build cannot silently migrate production.
- "What is running, and which commit is it" has an exact answer.
- Environment credentials are isolated by construction.

**Negative, accepted**

- A registry is now part of the deployment path. CI needs push credentials,
  and an air-gapped installation needs an internal registry — the same
  constraint the engine download already has.
- Two environments mean configuring the platform twice. That is inherent to
  configuration being environment state; the import command reduces it to one
  command per environment.
- Production upgrades gain a step. Deliberate, and documented.
- Version tags have to be created by someone. The release workflow is
  triggered by pushing a tag, so this is one command, but it is not automatic.

## Alternatives considered

**Rebuild from `main` for production.** Rejected: production then runs an
image nobody tested. Reproducible builds narrow the gap but do not close it —
base images and the engine download move underneath.

**A long-lived `staging` branch between `dev` and `main`.** Rejected: a third
branch to keep merged, solving a problem tags already solve. Adding an
environment should not add a branch.

**Environment-specific values committed to the repository.** Rejected. It is
the thing [docs/branching.md](../branching.md) exists to prevent: the moment
`values-prod.yaml` is tracked, `main` and `dev` diverge on it forever, and
production hostnames live in a public repository. `.example` files are
tracked; real values are not.

**Auto-migrate everywhere, and rely on migrations being backwards
compatible.** Rejected as a rule rather than a practice: it is correct until
one migration is not, and the cost of that single exception is a production
outage during a deploy.

**One database with a schema per environment.** Rejected: a shared instance
makes a dev mistake a production incident, and it defeats the point of
separate `SECRETS_KEY` values since both schemas sit behind one set of
credentials.
