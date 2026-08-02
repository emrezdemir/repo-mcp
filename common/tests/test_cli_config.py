"""Tests for the configuration commands of `repo-mcp-admin`.

The point of these is parity: the terminal and the web interface must be able
to do the same things, so the commands are exercised end to end through
`main()` — argparse included — against a real SQLite database, and the effect
is then read back through the same store the running services read.

They also pin the two behaviours that are easy to lose in a refactor: a
rejected operation exits non-zero with a message rather than a traceback, and
a secret's value is never printed.
"""

from __future__ import annotations

import asyncio

import pytest
from cryptography.fernet import Fernet

from repo_mcp_common.cli import main
from repo_mcp_common.db import Database
from repo_mcp_common.env import DatabaseEnv
from repo_mcp_common.store import ConfigStore


@pytest.fixture
def key(monkeypatch) -> str:
    value = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", value)
    return value


@pytest.fixture
def database_url(tmp_path, key, monkeypatch) -> str:
    """`main()` builds its own Database from the environment, as a user would."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'config.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CONFIG_POLL_SECONDS", "0")
    assert main(["init-db"]) == 0
    return url


def store_for(url: str) -> ConfigStore:
    env = DatabaseEnv(
        url=url,
        pool_size=1,
        pool_max_overflow=0,
        config_poll_seconds=0,
        connect_retry_seconds=5,
    )
    return ConfigStore(Database(env), poll_seconds=0)


def snapshot(url: str):
    """Read the configuration back the way a running service does.

    Synchronous on purpose: `main()` owns an event loop of its own, so these
    tests cannot be coroutines and this helper has to bring its own.
    """

    async def read():
        store = store_for(url)
        try:
            return await store.snapshot()
        finally:
            await store._db.aclose()

    return asyncio.run(read())


# ── squads ───────────────────────────────────────────────────────────


def test_squad_set_reaches_the_configuration_services_read(database_url):
    assert main(
        [
            "squad", "set", "payments",
            "--group", "squad-payments",
            "--project", "acme-payments-*",
            "--profile", "analysis",
        ]
    ) == 0

    document = (snapshot(database_url)).tenants_document
    assert document["tenants"]["payments"]["ldap_groups"] == ["squad-payments"]
    assert document["tenants"]["payments"]["projects"] == ["acme-payments-*"]


def test_squad_set_refuses_a_group_that_belongs_to_another_squad(database_url, capsys):
    assert main(["squad", "set", "a", "--group", "shared", "--project", "x"]) == 0
    assert main(["squad", "set", "b", "--group", "shared", "--project", "y"]) == 1

    # A rejection is a message, not a traceback: this runs in a terminal.
    assert "already mapped" in capsys.readouterr().err


def test_squad_remove(database_url):
    assert main(["squad", "set", "gone", "--group", "g", "--project", "p"]) == 0
    assert main(["squad", "remove", "gone"]) == 0
    assert (snapshot(database_url)).tenants_document["tenants"] == {}


def test_squad_remove_reports_a_squad_that_is_not_there(database_url, capsys):
    assert main(["squad", "remove", "nosuch"]) == 1
    assert "no tenant named" in capsys.readouterr().err


# ── roles ────────────────────────────────────────────────────────────


def test_role_set_replaces_rather_than_appends(database_url):
    assert main(["role", "set", "qa", "--group", "one", "--group", "two"]) == 0
    assert main(["role", "set", "qa", "--group", "two"]) == 0

    roles = (snapshot(database_url)).tenants_document["roles"]
    assert roles["qa"] == ["two"]


def test_role_set_rejects_a_role_the_platform_does_not_have(database_url, capsys):
    # argparse refuses before any database work, which is the right place.
    with pytest.raises(SystemExit):
        main(["role", "set", "wizard", "--group", "g"])
    assert "invalid choice" in capsys.readouterr().err


# ── connectors ───────────────────────────────────────────────────────


def test_connector_set_parses_repeated_settings(database_url):
    assert main(["squad", "set", "payments", "--group", "g", "--project", "p"]) == 0
    assert main(
        [
            "connector", "set", "acme-github",
            "--provider", "github",
            "--squad", "payments",
            "--setting", "org=acme",
            "--setting", "per_page=50",
            "--include", "acme-*",
        ]
    ) == 0

    # Provider settings are flattened into the connector entry, which is the
    # shape ScanConfig.from_dict has always taken.
    connectors = (snapshot(database_url)).scan_document["connectors"]
    assert connectors[0]["org"] == "acme"
    assert connectors[0]["per_page"] == 50
    assert connectors[0]["include"] == ["acme-*"]


def test_connector_set_refuses_a_squad_that_does_not_exist(database_url, capsys):
    assert main(["connector", "set", "c", "--provider", "github", "--squad", "nosuch"]) == 1
    assert "create the squad first" in capsys.readouterr().err


def test_connector_remove(database_url):
    assert main(["squad", "set", "s", "--group", "g", "--project", "p"]) == 0
    assert main(["connector", "set", "c", "--provider", "github", "--squad", "s"]) == 0
    assert main(["connector", "remove", "c"]) == 0
    assert (snapshot(database_url)).scan_document["connectors"] == []


# ── secrets ──────────────────────────────────────────────────────────


def test_secret_set_stores_a_value_that_the_services_can_read(database_url):
    assert main(["secret", "set", "token", "--value", "s3cret", "--description", "a token"]) == 0
    assert (snapshot(database_url)).secrets["token"] == "s3cret"


def test_secret_list_never_prints_a_value(database_url, capsys):
    assert main(["secret", "set", "token", "--value", "s3cret"]) == 0
    capsys.readouterr()

    assert main(["secret", "list"]) == 0
    assert "s3cret" not in capsys.readouterr().out


def test_secret_remove(database_url):
    assert main(["secret", "set", "token", "--value", "v"]) == 0
    assert main(["secret", "remove", "token"]) == 0
    assert "token" not in (snapshot(database_url)).secrets


# ── settings, audit, administrators ──────────────────────────────────


def test_settings_shows_where_each_value_came_from(database_url, capsys):
    assert main(["set", "litellm.model", "gpt-4o"]) == 0
    capsys.readouterr()

    assert main(["settings"]) == 0
    lines = {
        line.split()[0]: line for line in capsys.readouterr().out.splitlines() if line.strip()
    }
    assert lines["litellm.model"].endswith("set")
    assert lines["oidc.audience"].endswith("default")


def test_audit_records_what_the_commands_did(database_url, capsys):
    assert main(["squad", "set", "payments", "--group", "g", "--project", "p"]) == 0
    capsys.readouterr()

    assert main(["audit", "--limit", "10"]) == 0
    out = capsys.readouterr().out
    assert "tenant.create" in out
    assert "cli" in out


def test_admins_lists_the_local_accounts(database_url, capsys, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "ada")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-enough-password")
    assert main(["create-admin"]) == 0
    capsys.readouterr()

    assert main(["admins"]) == 0
    out = capsys.readouterr().out
    assert "ada" in out
    assert "never" in out


def test_answer_cache_reports_an_empty_cache(database_url, capsys):
    assert main(["answer-cache"]) == 0
    assert "entries:  0" in capsys.readouterr().out


# ── the reason all of this exists ────────────────────────────────────


def test_every_admin_api_operation_has_a_command():
    """Parity, checked rather than asserted in a document.

    The web interface calls the routes in gateway/app/admin_api.py; a terminal
    calls these. If a route gains an operation and this list does not, the gap
    is exactly the kind that is discovered by a user rather than by a test.
    """
    from repo_mcp_common.cli import build_parser

    parser = build_parser()
    actions = {a.dest: a for a in parser._actions}
    commands = set(actions["command"].choices)

    for expected in (
        "squad", "role", "connector", "secret", "settings", "set", "audit",
        "admins", "answer-cache", "create-admin", "set-password",
    ):
        assert expected in commands, f"{expected} is in the admin API but not in the CLI"


def test_a_configuration_change_bumps_the_generation(database_url):
    before = (snapshot(database_url)).generation
    assert main(["squad", "set", "s", "--group", "g", "--project", "p"]) == 0
    after = (snapshot(database_url)).generation
    # This is what makes a running gateway notice a change made from a
    # terminal, without a restart.
    assert after > before
