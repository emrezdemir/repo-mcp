"""`repo-mcp-admin` — reading and changing the running configuration.

Everything an administrator can do in the web interface is here, and the other
way round: both surfaces call the same functions in `admin.py`, so a squad
created from a terminal and one created from a browser are the same row,
validated by the same rules and recorded in the same audit table.

A change made here reaches the running services without a restart. Both watch
the generation counter and reload when it moves, so the delay is one poll
interval (`CONFIG_POLL_SECONDS`, five seconds by default).
"""

from __future__ import annotations

import getpass
import json
import sys

from sqlalchemy import select

from .admin import (
    VALID_MODES,
    VALID_PROFILES,
    VALID_PROVIDERS,
    VALID_ROLES,
    AdminError,
    ConnectorInput,
    TenantInput,
    delete_connector,
    delete_secret,
    delete_tenant,
    put_secret,
    set_role_groups,
    upsert_connector,
    upsert_tenant,
)
from .answer_cache import purge as purge_answers
from .answer_cache import stats as cache_stats
from .db import Database
from .models import (
    AdminUser,
    AuditEntry,
    Connector,
    RoleAssignment,
    Secret,
    Setting,
    Tenant,
)
from .store import DEFAULT_SETTINGS

ACTOR = "cli"


def _print(message: str = "") -> None:
    print(message, file=sys.stdout)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _table(headers: list[str], rows: list[list[str]]) -> None:
    """Columns wide enough for their content, which is all a terminal needs."""
    if not rows:
        _print("  (none)")
        return
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    _print("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    _print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        _print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())


def _pairs(values: list[str] | None) -> dict:
    """`--setting key=value` repeated, with JSON values where they parse."""
    out: dict = {}
    for item in values or []:
        key, _, raw = item.partition("=")
        if not _:
            raise AdminError(f"expected key=value, got {item!r}")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


async def _with_database(work):
    database = Database()
    await database.wait_until_ready()
    try:
        return await work(database)
    finally:
        await database.aclose()


# ── squads ───────────────────────────────────────────────────────────


async def cmd_squad_list(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            tenants = (await session.execute(select(Tenant))).scalars().all()
            rows = [
                [
                    t.name,
                    t.tool_profile,
                    "yes" if t.enabled else "no",
                    "yes" if t.structural_only else "no",
                    ", ".join(sorted(g.group_name for g in t.ldap_groups)),
                    ", ".join(sorted(p.pattern for p in t.projects)),
                ]
                for t in sorted(tenants, key=lambda t: t.name)
            ]
        _table(["NAME", "PROFILE", "ENABLED", "STRUCTURAL", "LDAP GROUPS", "PROJECTS"], rows)
        return 0

    return await _with_database(work)


async def cmd_squad_set(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await upsert_tenant(
                session,
                TenantInput(
                    name=args.name,
                    ldap_groups=args.group,
                    projects=args.project,
                    tool_profile=args.profile,
                    structural_only=args.structural_only,
                    denied_tools=args.deny,
                    litellm_key_secret=args.litellm_key_secret,
                    enabled=not args.disabled,
                ),
                actor=ACTOR,
            )
        _print(f"squad {args.name} saved")
        return 0

    return await _with_database(work)


async def cmd_squad_remove(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await delete_tenant(session, args.name, actor=ACTOR)
        _print(f"squad {args.name} removed")
        return 0

    return await _with_database(work)


# ── roles ────────────────────────────────────────────────────────────


async def cmd_role_list(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            rows = (await session.execute(select(RoleAssignment))).scalars().all()
        groups: dict[str, list[str]] = {role: [] for role in sorted(VALID_ROLES)}
        for row in rows:
            groups.setdefault(row.role, []).append(row.group_name)
        rows = [
            [role, ", ".join(sorted(names)) or "(none)"] for role, names in sorted(groups.items())
        ]
        _table(["ROLE", "LDAP GROUPS"], rows)
        return 0

    return await _with_database(work)


async def cmd_role_set(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await set_role_groups(session, args.role, args.group, actor=ACTOR)
        _print(f"role {args.role}: {', '.join(args.group) or 'no groups'}")
        return 0

    return await _with_database(work)


# ── connectors ───────────────────────────────────────────────────────


async def cmd_connector_list(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            connectors = (await session.execute(select(Connector))).scalars().all()
            rows = [
                [
                    c.name,
                    c.provider,
                    c.tenant.name,
                    c.mode,
                    "yes" if c.enabled else "no",
                    c.token_secret or "-",
                    json.dumps(c.settings, sort_keys=True),
                ]
                for c in sorted(connectors, key=lambda c: c.name)
            ]
        _table(["NAME", "PROVIDER", "SQUAD", "MODE", "ENABLED", "TOKEN SECRET", "SETTINGS"], rows)
        return 0

    return await _with_database(work)


async def cmd_connector_set(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await upsert_connector(
                session,
                ConnectorInput(
                    name=args.name,
                    provider=args.provider,
                    tenant=args.squad,
                    settings=_pairs(args.setting),
                    token_secret=args.token_secret,
                    include=args.include or ["*"],
                    exclude=args.exclude or [],
                    mode=args.mode,
                    persistence=not args.no_persistence,
                    enabled=not args.disabled,
                ),
                actor=ACTOR,
            )
        _print(f"connector {args.name} saved")
        return 0

    return await _with_database(work)


async def cmd_connector_remove(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await delete_connector(session, args.name, actor=ACTOR)
        _print(f"connector {args.name} removed")
        return 0

    return await _with_database(work)


# ── secrets ──────────────────────────────────────────────────────────


async def cmd_secret_list(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            rows = (await session.execute(select(Secret))).scalars().all()
        # Names and descriptions. A value that has been stored is never shown
        # again, here or anywhere else.
        _table(
            ["NAME", "DESCRIPTION"],
            [[s.name, s.description or ""] for s in sorted(rows, key=lambda s: s.name)],
        )
        return 0

    return await _with_database(work)


async def cmd_secret_set(args) -> int:
    value = args.value
    if value is None:
        if not sys.stdin.isatty():
            # Reading it from a pipe keeps it out of the shell history, which
            # is the point of not accepting it as an argument by default.
            value = sys.stdin.read().strip()
        else:
            value = getpass.getpass(f"Value for {args.name}: ")
    if not value:
        return _fail("a secret needs a value")

    async def work(database: Database) -> int:
        async with database.session() as session:
            await put_secret(
                session, args.name, value, actor=ACTOR, description=args.description
            )
        _print(f"secret {args.name} stored")
        return 0

    return await _with_database(work)


async def cmd_secret_remove(args) -> int:
    async def work(database: Database) -> int:
        async with database.session() as session:
            await delete_secret(session, args.name, actor=ACTOR)
        _print(f"secret {args.name} removed")
        return 0

    return await _with_database(work)


# ── settings, audit, administrators, answer cache ────────────────────


async def cmd_settings(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            stored = {
                row.key: row.value for row in (await session.execute(select(Setting))).scalars()
            }
        rows = []
        for key, default in sorted(DEFAULT_SETTINGS.items()):
            value = stored.get(key, default)
            rows.append([key, json.dumps(value), "set" if key in stored else "default"])
        _table(["KEY", "VALUE", "SOURCE"], rows)
        return 0

    return await _with_database(work)


async def cmd_audit(args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            rows = (
                await session.execute(
                    select(AuditEntry).order_by(AuditEntry.at.desc()).limit(args.limit)
                )
            ).scalars().all()
        _table(
            ["WHEN", "WHO", "WHAT", "TARGET"],
            [
                [
                    row.at.isoformat(timespec="seconds") if row.at else "",
                    row.actor,
                    row.action,
                    row.target or "",
                ]
                for row in rows
            ],
        )
        return 0

    return await _with_database(work)


async def cmd_admin_list(_args) -> int:
    async def work(database: Database) -> int:
        async with database.read() as session:
            rows = (await session.execute(select(AdminUser))).scalars().all()
        _table(
            ["USERNAME", "ACTIVE", "MUST CHANGE PASSWORD", "LAST LOGIN"],
            [
                [
                    user.username,
                    "yes" if user.is_active else "no",
                    "yes" if user.must_change_password else "no",
                    user.last_login_at.isoformat(timespec="seconds")
                    if user.last_login_at
                    else "never",
                ]
                for user in sorted(rows, key=lambda u: u.username)
            ],
        )
        return 0

    return await _with_database(work)


async def cmd_answer_cache(args) -> int:
    async def work(database: Database) -> int:
        if args.purge:
            async with database.session() as session:
                removed = await purge_answers(
                    session, tenant=args.squad, project=args.project
                )
            _print(f"removed {removed} cached answer(s)")
            return 0

        async with database.read() as session:
            summary = await cache_stats(session)
        _print(f"entries:  {summary['entries']}")
        _print(f"hits:     {summary['hits']}")
        _print(f"squads:   {', '.join(summary['squads']) or 'none'}")
        return 0

    return await _with_database(work)


# ── parser ───────────────────────────────────────────────────────────


def register(sub) -> dict:
    """Add the configuration commands and return their dispatch table.

    Nested subcommands are keyed as "squad set" and so on, which is what
    `main` looks up after argparse has filled in `args.command`.
    """
    commands: dict = {}

    # ── squad ────────────────────────────────────────────────────────
    squad = sub.add_parser("squad", help="list, create or remove a squad")
    squad_sub = squad.add_subparsers(dest="subcommand", required=True)
    squad_sub.add_parser("list", help="show every squad")

    squad_set = squad_sub.add_parser("set", help="create or update a squad")
    squad_set.add_argument("name")
    squad_set.add_argument(
        "--group", action="append", required=True, metavar="LDAP_GROUP",
        help="an LDAP group whose members belong to this squad; repeatable",
    )
    squad_set.add_argument(
        "--project", action="append", required=True, metavar="PATTERN",
        help="a project name or glob this squad may read; repeatable",
    )
    squad_set.add_argument(
        "--profile", default="analysis", choices=sorted(VALID_PROFILES),
        help="the engine tool profile (default: analysis)",
    )
    squad_set.add_argument(
        "--structural-only", action="store_true",
        help="refuse the tools that return source code",
    )
    squad_set.add_argument(
        "--deny", action="append", metavar="TOOL", help="deny one tool; repeatable"
    )
    squad_set.add_argument("--litellm-key-secret", help="secret holding this squad's LiteLLM key")
    squad_set.add_argument("--disabled", action="store_true", help="store it, but refuse requests")

    squad_remove = squad_sub.add_parser("remove", help="delete a squad")
    squad_remove.add_argument("name")

    # ── role ─────────────────────────────────────────────────────────
    role = sub.add_parser("role", help="list or set the groups behind a role")
    role_sub = role.add_subparsers(dest="subcommand", required=True)
    role_sub.add_parser("list", help="show every role and its groups")
    role_set = role_sub.add_parser("set", help="replace a role's groups")
    role_set.add_argument("role", choices=sorted(VALID_ROLES))
    role_set.add_argument(
        "--group", action="append", default=[], metavar="LDAP_GROUP",
        help="repeatable; passing none clears the role",
    )

    # ── connector ────────────────────────────────────────────────────
    connector = sub.add_parser("connector", help="list, create or remove a connector")
    connector_sub = connector.add_subparsers(dest="subcommand", required=True)
    connector_sub.add_parser("list", help="show every connector")

    connector_set = connector_sub.add_parser("set", help="create or update a connector")
    connector_set.add_argument("name")
    connector_set.add_argument("--provider", required=True, choices=sorted(VALID_PROVIDERS))
    connector_set.add_argument("--squad", required=True, help="the squad its repositories go to")
    connector_set.add_argument(
        "--setting", action="append", metavar="KEY=VALUE",
        help="provider setting, such as org=acme or base_url=…; repeatable",
    )
    connector_set.add_argument("--token-secret", help="secret holding the access token")
    connector_set.add_argument(
        "--include", action="append", metavar="GLOB", help="repository glob to index; repeatable"
    )
    connector_set.add_argument(
        "--exclude", action="append", metavar="GLOB", help="repository glob to skip; repeatable"
    )
    connector_set.add_argument("--mode", default="moderate", choices=sorted(VALID_MODES))
    connector_set.add_argument(
        "--no-persistence", action="store_true", help="do not write a shareable graph artifact"
    )
    connector_set.add_argument("--disabled", action="store_true", help="store it, but do not scan")

    connector_remove = connector_sub.add_parser("remove", help="delete a connector")
    connector_remove.add_argument("name")

    # ── secret ───────────────────────────────────────────────────────
    secret = sub.add_parser("secret", help="list, store or remove a secret")
    secret_sub = secret.add_subparsers(dest="subcommand", required=True)
    secret_sub.add_parser("list", help="show secret names, never values")
    secret_set = secret_sub.add_parser("set", help="store a secret value")
    secret_set.add_argument("name")
    secret_set.add_argument(
        "--value", help="the value; omit to be prompted, or to read it from stdin"
    )
    secret_set.add_argument("--description", help="what it is for")
    secret_remove = secret_sub.add_parser("remove", help="delete a secret")
    secret_remove.add_argument("name")

    # ── flat commands ────────────────────────────────────────────────
    sub.add_parser("settings", help="show every setting, its value and where it came from")
    sub.add_parser("admins", help="show the local administrator accounts")

    audit = sub.add_parser("audit", help="show recent configuration changes")
    audit.add_argument("--limit", type=int, default=25)

    cache = sub.add_parser("answer-cache", help="show or purge the cached answers")
    cache.add_argument(
        "--purge", action="store_true", help="delete entries instead of showing them"
    )
    cache.add_argument("--squad", help="limit the purge to one squad")
    cache.add_argument("--project", help="limit the purge to one project")

    commands.update(
        {
            "squad list": cmd_squad_list,
            "squad set": cmd_squad_set,
            "squad remove": cmd_squad_remove,
            "role list": cmd_role_list,
            "role set": cmd_role_set,
            "connector list": cmd_connector_list,
            "connector set": cmd_connector_set,
            "connector remove": cmd_connector_remove,
            "secret list": cmd_secret_list,
            "secret set": cmd_secret_set,
            "secret remove": cmd_secret_remove,
            "settings": cmd_settings,
            "admins": cmd_admin_list,
            "audit": cmd_audit,
            "answer-cache": cmd_answer_cache,
        }
    )
    return commands
