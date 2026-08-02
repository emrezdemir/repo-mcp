# repo-mcp-common

The shared layer both services depend on: the configuration database, its
migrations, secret encryption, the bootstrap flow and the `repo-mcp-admin`
command.

Part of [repo-mcp](../README.md). Why configuration lives in PostgreSQL rather
than in files is [ADR-0006](../docs/adr/0006-configuration-in-the-database.md).

## Layout

| Module | Responsibility |
| --- | --- |
| `models.py` | SQLAlchemy schema: tenants, roles, connectors, secrets, settings, administrators, audit |
| `db.py` | Async engine, sessions, startup retry |
| `store.py` | Reads the database into the document shapes the services consume, cached by generation |
| `admin.py` | Write operations; every mutation bumps the generation counter |
| `bootstrap.py` | Schema upgrade, first administrator, YAML import |
| `crypto.py` | Fernet encryption for stored credentials |
| `passwords.py` | Argon2id hashing and the password policy |
| `env.py` | The few variables that must be known before the database can be read |
| `cli.py` | `repo-mcp-admin` |
| `migrations/` | Alembic |

## The environment / database split

Only what is needed *before* the database can be read stays in the
environment:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Where the configuration lives. Bundled PostgreSQL or your own. |
| `SECRETS_KEY` | Fernet key for credentials at rest. Must be stable and identical on every replica. |
| `CBM_*`, `PORT`, `LOG_LEVEL` | Engine paths and process settings |

Everything else — tenants, roles, connectors, OIDC and LiteLLM settings,
tunables, provider tokens — is administrator-editable and lives in the
database.

## Commands

```bash
repo-mcp-admin generate-key            # a new SECRETS_KEY
repo-mcp-admin init                    # schema + first administrator
repo-mcp-admin status                  # what is configured right now
repo-mcp-admin import --tenants deploy/tenants.yaml --scan deploy/scan.yaml
repo-mcp-admin set litellm.model '"ollama/qwen2.5-coder:14b"'
repo-mcp-admin set-password admin
```

Every command is safe to re-run.

## Tests

```bash
pip install -e '.[dev]' && pytest
```

Tests run against SQLite via `aiosqlite`, so they need no database server. The
schema is created by the same Alembic migration PostgreSQL gets.
