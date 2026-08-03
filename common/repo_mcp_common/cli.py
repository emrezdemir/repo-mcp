"""`repo-mcp-admin` — schema, the first administrator, and seeding.

Everything here is safe to re-run. The Compose stack calls `init` on start, so
a fresh deployment reaches a usable state without anyone reading a runbook.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from . import bootstrap as boot
from . import cli_config
from .admin import AdminError, set_setting
from .crypto import generate_key
from .db import Database, DatabaseUnavailable
from .env import EnvError, migrate_on_start, secrets_key
from .passwords import WeakPassword, validate


def _print(message: str = "") -> None:
    print(message, file=sys.stdout)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


# ── commands ─────────────────────────────────────────────────────────


async def cmd_init_db(_args) -> int:
    database = Database()
    await database.wait_until_ready()
    await boot.upgrade_schema(database)
    await database.aclose()
    _print("schema is up to date")
    return 0


async def cmd_create_admin(args) -> int:
    database = Database()
    await database.wait_until_ready()
    if migrate_on_start():
        await boot.upgrade_schema(database)

    if await boot.has_admin(database) and not args.force:
        await database.aclose()
        _print("an administrator already exists; nothing to do")
        _print("use 'repo-mcp-admin set-password' to change a password")
        return 0

    username = args.username or os.getenv("ADMIN_USERNAME") or ""
    password = args.password or os.getenv("ADMIN_PASSWORD") or ""

    if not username:
        if not sys.stdin.isatty():
            await database.aclose()
            return _fail(
                "no username given. Pass --username, set ADMIN_USERNAME, or run "
                "this interactively."
            )
        username = input("Administrator username [admin]: ").strip() or "admin"

    if not password and sys.stdin.isatty():
        while True:
            password = getpass.getpass("Password (blank to generate one): ")
            if not password:
                break
            try:
                validate(password)
            except WeakPassword as exc:
                _print(f"  {exc}")
                continue
            if password != getpass.getpass("Repeat password: "):
                _print("  passwords did not match")
                continue
            break

    try:
        created = await boot.ensure_admin(database, username, password or None)
    except (AdminError, WeakPassword) as exc:
        await database.aclose()
        return _fail(str(exc))
    finally:
        pass

    await database.aclose()

    if created is None:
        _print("an administrator already exists; nothing to do")
        return 0

    _print("")
    _print(f"  administrator created: {created.username}")
    if created.generated:
        _print(f"  generated password:    {created.password}")
        _print("")
        _print("  Store it now — it is not shown again and is not recoverable.")
    _print("")
    return 0


async def cmd_set_password(args) -> int:
    from .admin import set_admin_password

    password = args.password or ""
    if not password:
        if not sys.stdin.isatty():
            return _fail("no password given; pass --password or run interactively")
        password = getpass.getpass("New password: ")

    database = Database()
    await database.wait_until_ready()
    try:
        async with database.session() as session:
            await set_admin_password(session, args.username, password, actor="cli")
    except (AdminError, WeakPassword) as exc:
        return _fail(str(exc))
    finally:
        await database.aclose()
    _print(f"password updated for {args.username}")
    return 0


async def cmd_import(args) -> int:
    database = Database()
    await database.wait_until_ready()
    if migrate_on_start():
        await boot.upgrade_schema(database)

    tenants_doc = boot.read_yaml(Path(args.tenants)) if args.tenants else None
    scan_doc = boot.read_yaml(Path(args.scan)) if args.scan else None
    if tenants_doc is None and scan_doc is None:
        await database.aclose()
        return _fail("nothing to import; pass --tenants and/or --scan")

    try:
        counts = await boot.import_documents(
            database, tenants_doc, scan_doc, secrets_from_env=not args.no_env_secrets
        )
    except AdminError as exc:
        await database.aclose()
        return _fail(str(exc))
    await database.aclose()

    _print(
        "imported: "
        + ", ".join(f"{value} {name}" for name, value in counts.items() if value)
        or "imported: nothing"
    )
    return 0


async def cmd_status(_args) -> int:
    database = Database()
    _print(f"database: {database.env.redacted_url()}")
    try:
        await database.wait_until_ready(timeout=10)
    except DatabaseUnavailable as exc:
        return _fail(str(exc))

    state = await boot.inspect_state(database)
    _print(f"schema:   {'present' if state.schema_present else 'missing'}")
    _print(f"admins:   {state.admin_count}")

    # Deliberately does not fail without it: diagnosing a deployment whose key
    # is missing is exactly when this command is worth running.
    try:
        secrets_key()
        _print("key:      set")
    except EnvError:
        _print("key:      MISSING — services will refuse to serve (SECRETS_KEY)")

    if state.ready:
        from .store import ConfigStore

        snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
        tenants = snapshot.tenants_document.get("tenants", {})
        connectors = snapshot.scan_document.get("connectors", [])
        _print(f"gen:      {snapshot.generation}")
        _print(f"tenants:  {', '.join(sorted(tenants)) or 'none'}")
        _print(f"conns:    {', '.join(c['name'] for c in connectors) or 'none'}")
        _print(f"secrets:  {len(snapshot.secrets)}")
    else:
        _print("")
        _print(state.explain())

    await database.aclose()
    return 0 if state.ready else 1


async def cmd_set(args) -> int:
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value  # a bare string is the common case

    database = Database()
    await database.wait_until_ready()
    async with database.session() as session:
        await set_setting(session, args.key, value, actor="cli")
    await database.aclose()
    _print(f"{args.key} = {value!r}")
    return 0


def cmd_generate_key(_args) -> int:
    _print(generate_key())
    return 0


async def cmd_init(args) -> int:
    """Everything a fresh deployment needs, in one command.

    Migrations are applied only when MIGRATE_ON_START allows it. Automatic
    migration is convenient in development and a liability in production: a
    migration that takes a table lock, or an older replica starting against a
    newer schema during a rollback, should not be discovered there. See
    docs/adr/0008-environments-and-promotion.md.
    """
    database = Database()
    await database.wait_until_ready()

    if migrate_on_start():
        await boot.upgrade_schema(database)
        _print("schema is up to date")
    else:
        state = await boot.inspect_state(database)
        if not state.schema_present:
            await database.aclose()
            return _fail(
                "the database has no schema and MIGRATE_ON_START is false.\n"
                "Run the migration deliberately:  repo-mcp-admin init-db"
            )
        _print("schema check skipped (MIGRATE_ON_START is false)")

    if not await boot.has_admin(database):
        password = args.password or os.getenv("ADMIN_PASSWORD") or ""
        if password or sys.stdin.isatty():
            # An explicit password (automation, enterprise) or an interactive
            # run: create the administrator here, as before.
            await database.aclose()
            return await cmd_create_admin(args)
        # No password and no terminal — the bundled 'make up' path. Leave the
        # first administrator for the web interface to create on first open, so
        # a fresh install is a browser away rather than a log to grep. Set
        # ADMIN_PASSWORD in deploy/.env to create it here instead.
        _print("no administrator yet")
        _print("create one in the browser at http://localhost:8080/ui on first open,")
        _print("or set ADMIN_PASSWORD in deploy/.env to create it here.")
        await database.aclose()
        return 0

    _print("an administrator already exists")
    await database.aclose()
    return 0


# ── entry point ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-mcp-admin",
        description="Manage the repo-mcp configuration database.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create or upgrade the schema")
    sub.add_parser("status", help="show database, schema and configuration state")
    sub.add_parser("generate-key", help="print a new SECRETS_KEY")

    init = sub.add_parser("init", help="upgrade the schema and create the first administrator")
    create = sub.add_parser("create-admin", help="create the first administrator")
    for command in (init, create):
        command.add_argument("--username", help="defaults to $ADMIN_USERNAME, then a prompt")
        command.add_argument("--password", help="defaults to $ADMIN_PASSWORD, then a prompt")
    create.add_argument(
        "--force", action="store_true", help="create even when an administrator exists"
    )
    init.add_argument("--force", action="store_true", help=argparse.SUPPRESS)

    password = sub.add_parser("set-password", help="change an administrator's password")
    password.add_argument("username")
    password.add_argument("--password")

    importer = sub.add_parser("import", help="seed the database from the YAML files")
    importer.add_argument("--tenants", help="path to tenants.yaml")
    importer.add_argument("--scan", help="path to scan.yaml")
    importer.add_argument(
        "--no-env-secrets",
        action="store_true",
        help="do not copy token values from the environment into the database",
    )

    setting = sub.add_parser("set", help="set a configuration value")
    setting.add_argument("key")
    setting.add_argument("value", help="JSON, or a bare string")

    # Squads, roles, connectors, secrets, settings, audit and the answer
    # cache: the same operations the web interface offers, through the same
    # functions. See cli_config.py.
    CONFIG_COMMANDS.update(cli_config.register(sub))

    return parser


COMMANDS = {
    "init-db": cmd_init_db,
    "init": cmd_init,
    "create-admin": cmd_create_admin,
    "set-password": cmd_set_password,
    "import": cmd_import,
    "status": cmd_status,
    "set": cmd_set,
}

#: Filled in by `build_parser`, because the handlers and the subparsers are
#: declared together in cli_config and it would be easy for two lists to drift.
CONFIG_COMMANDS: dict = {}


def _dispatch_key(args) -> str:
    """"squad" plus "set" is the command "squad set"; a flat command is itself."""
    sub = getattr(args, "subcommand", None)
    return f"{args.command} {sub}" if sub else args.command


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "generate-key":
        return cmd_generate_key(args)

    handler = COMMANDS.get(args.command) or CONFIG_COMMANDS.get(_dispatch_key(args))
    if handler is None:  # pragma: no cover — argparse rejects unknown commands first
        return _fail(f"unknown command {_dispatch_key(args)!r}")

    try:
        return asyncio.run(handler(args))
    except AdminError as exc:
        return _fail(str(exc))
    except EnvError as exc:
        return _fail(str(exc))
    except DatabaseUnavailable as exc:
        return _fail(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
