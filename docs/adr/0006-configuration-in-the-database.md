# ADR-0006: Configuration lives in PostgreSQL, not in files

- **Status:** Accepted
- **Context:** Tenants, roles, connectors and tunables were YAML files read once
  at startup. Changing anything meant editing a file on the host and
  restarting.

## Context

`tenants.yaml` and `scan.yaml` worked while the platform was operated by the
person who deployed it. They stop working as soon as an administrator who is
not that person needs to onboard a squad, rotate a provider token or adjust a
timeout:

- Every change is a file edit plus a restart, which means shell access to a
  production host for what is an ordinary administrative act.
- Two replicas can disagree, because nothing guarantees they read the same
  file.
- There is no history: who added this tenant, and when?
- Provider tokens have to sit in the environment of every pod that might need
  them.

The platform already assumes a stateful deployment — the graph stores are on
disk — so a database is not a new class of dependency.

## Decision

Configuration moves into PostgreSQL. An administrative API reads and writes
it, and both services read it at runtime through a cached repository.

**The split is by bootstrap order, not by taste:**

| Where | What | Why |
| --- | --- | --- |
| Environment | `DATABASE_URL`, `SECRETS_KEY`, bind port, log level, engine binary and storage paths | Needed *before* the database can be read. Putting them in the database is a chicken-and-egg. |
| Database | Tenants, roles, project allowlists, connectors, OIDC settings, LiteLLM settings, tunables, provider secrets | Everything an administrator changes during normal operation. |

Provider tokens and webhook secrets are stored encrypted with Fernet, keyed by
`SECRETS_KEY` from the environment. The database never holds plaintext
credentials, and a database backup is not by itself a credential leak.

YAML is retained as an **import format only**: `repo-mcp-admin import` seeds an
empty database from the existing `.example` files. Nothing reads YAML at
runtime any more.

Both services cache configuration and re-read it when a generation counter in
the database changes, so an administrative edit reaches every replica within
one poll interval without a restart.

## Rationale

**PostgreSQL rather than SQLite.** The graph stores are already SQLite and
already constrain the storage topology
([ADR-0005](0005-storage-topology.md)); adding a second SQLite database that
several replicas must write would make the same problem worse. PostgreSQL is
the boring choice, is what an operations team already runs, and removes the
"do not put this on NFS" caveat for the configuration path.

**Bundled by default, external when wanted.** The Compose stack ships a
PostgreSQL container so `make up` works with no external dependency. Setting
`DATABASE_URL` at a managed instance switches to it with no code change — the
same variable, the same schema, the same migrations.

**Migrations, not "create table if not exists".** Alembic gives an upgrade
path and a downgrade, and makes a schema change reviewable in a diff. Ad-hoc
DDL at startup is how schemas silently diverge between environments.

**Encryption at rest for secrets.** An admin API that manages GitHub tokens
will hold GitHub tokens. Keeping the key in the environment means database
access alone is not enough to use them, and a dump handed to a support
engineer is not a credential handout.

**Configuration remains untracked.** The property from
[docs/branching.md](../branching.md) — that `main` and `dev` never conflict
over environment values — is strengthened, not weakened: configuration is now
not in git at all, in any form.

## Consequences

**Positive**

- Administration happens through an API, not shell access to a host.
- All replicas read one source, so they cannot disagree.
- Every change is attributable and timestamped.
- Provider credentials are encrypted at rest and centrally rotatable.
- Adding the web UI later is now an API client rather than a new subsystem.

**Negative, accepted**

- A new hard dependency. Neither service starts without a reachable database;
  previously the gateway needed only a file. Health checks and the Helm chart
  account for it, and the failure message names the cause.
- A new secret to manage. Losing `SECRETS_KEY` means re-entering every
  provider token. Documented, and the bootstrap command refuses to run without
  it.
- Configuration changes are no longer visible in a git diff. The audit trail
  moves to the database and the audit log. For teams that want review before
  change, the import command still accepts YAML.
- Cached configuration means an edit is visible after up to one poll interval
  rather than instantly.
- More surface: migrations, an admin API and password handling are all new
  code that has to be correct.

## Alternatives considered

**Keep YAML and add a file watcher.** Rejected. It solves the restart but none
of the rest: still needs host access, still allows replicas to disagree, still
no history, and provider tokens stay in every pod's environment.

**Configuration in a ConfigMap, edited with `kubectl`.** Rejected for the same
reasons plus one: it makes Kubernetes access a prerequisite for an ordinary
administrative task, which is a much larger grant than "may edit tenants".

**Consul or etcd.** Rejected. Correct for the job, but a second stateful
system to operate for a workload that is a few hundred rows and needs
relational integrity between tenants, roles and projects anyway.

**SQLite for configuration too.** Rejected: several replicas writing one
SQLite file over shared storage is exactly the failure mode
[ADR-0005](0005-storage-topology.md) exists to avoid.

**Store secrets in the database in plaintext and rely on database access
control.** Rejected. It makes every backup, every replica and every support
dump a credential disclosure, and it removes any possibility of handing
someone read access for debugging.
