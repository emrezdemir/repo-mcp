"""Tests for the answer cache.

The interesting properties are the ones that make caching an LLM answer safe
at all: it never crosses a squad, a reindex retires it, and a merely similar
question does not silently become the same question.

Against SQLite, like the rest of the `common` tests — the schema is the same
Alembic migration PostgreSQL gets. See docs/adr/0009-answer-cache.md.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from repo_mcp_common import bootstrap as boot
from repo_mcp_common.answer_cache import (
    CacheKey,
    bump_epoch,
    cosine,
    current_epoch,
    lookup,
    normalise,
    pack,
    purge,
    purge_superseded,
    question_hash,
    store,
    unpack,
)
from repo_mcp_common.db import Database
from repo_mcp_common.env import DatabaseEnv


@pytest.fixture
def key(monkeypatch) -> str:
    value = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", value)
    return value


@pytest.fixture
async def database(tmp_path, key) -> Database:
    env = DatabaseEnv(
        url=f"sqlite+aiosqlite:///{tmp_path / 'cache.db'}",
        pool_size=1,
        pool_max_overflow=0,
        config_poll_seconds=0,
        connect_retry_seconds=5,
    )
    db = Database(env)
    await db.wait_until_ready()
    await boot.upgrade_schema(db)
    yield db
    await db.aclose()


def key_for(tenant: str = "payments", project: str = "api", epoch: int = 1) -> CacheKey:
    return CacheKey(tenant=tenant, project=project, tool="ask_codebase", epoch=epoch)


async def put(db: Database, cache_key: CacheKey, question: str, answer: str, **kwargs) -> None:
    async with db.session() as session:
        await store(session, cache_key, question, answer, answer_model="test-model", **kwargs)


# ── normalisation and vectors ────────────────────────────────────────


def test_normalisation_folds_case_and_whitespace():
    assert normalise("  How   does AUTH work? ") == "how does auth work?"
    assert question_hash("How does auth work?") == question_hash("how  does   auth work?")


def test_normalisation_does_not_reorder_words():
    """"Does A call B" and "does B call A" are different questions."""
    assert question_hash("does a call b") != question_hash("does b call a")


def test_a_vector_survives_a_round_trip():
    original = [0.5, -0.25, 1.0, 0.0]
    assert unpack(pack(original)) == pytest.approx(original)


def test_cosine_is_one_for_identical_and_zero_for_orthogonal():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_refuses_to_compare_different_dimensions():
    """A score between two spaces is a number with no meaning; 0.0 is a miss."""
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_of_a_zero_vector_is_zero_not_an_error():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── exact tier ───────────────────────────────────────────────────────


async def test_an_identical_question_is_recalled(database):
    await put(database, key_for(), "How does auth work?", "It uses OIDC.")
    async with database.session() as session:
        hit = await lookup(session, key_for(), "  how does AUTH work? ")
    assert hit is not None
    assert hit.kind == "exact"
    assert hit.answer == "It uses OIDC."


async def test_a_different_question_is_a_miss(database):
    await put(database, key_for(), "How does auth work?", "It uses OIDC.")
    async with database.session() as session:
        assert await lookup(session, key_for(), "How does billing work?") is None


async def test_storing_the_same_question_twice_replaces_the_answer(database):
    await put(database, key_for(), "How does auth work?", "Old answer.")
    await put(database, key_for(), "How does auth work?", "New answer.")
    async with database.session() as session:
        hit = await lookup(session, key_for(), "How does auth work?")
    assert hit is not None
    assert hit.answer == "New answer."


# ── isolation ────────────────────────────────────────────────────────


async def test_a_cached_answer_never_crosses_a_squad(database):
    """The whole tenancy model exists to stop this. A cache must not undo it."""
    await put(database, key_for(tenant="payments"), "How does auth work?", "Payments answer.")
    async with database.session() as session:
        assert await lookup(session, key_for(tenant="checkout"), "How does auth work?") is None


async def test_a_cached_answer_never_crosses_a_project(database):
    await put(database, key_for(project="api"), "Where is the retry logic?", "In api.")
    async with database.session() as session:
        assert await lookup(session, key_for(project="web"), "Where is the retry logic?") is None


async def test_a_cached_answer_never_crosses_a_tool(database):
    await put(database, key_for(), "What changed?", "An answer.")
    other = CacheKey(tenant="payments", project="api", tool="explain_change_impact", epoch=1)
    async with database.session() as session:
        assert await lookup(session, other, "What changed?") is None


# ── invalidation ─────────────────────────────────────────────────────


async def test_a_reindex_retires_the_previous_graph_s_answers(database):
    async with database.session() as session:
        epoch = await bump_epoch(session, "payments", "api")
    await put(database, key_for(epoch=epoch), "How does auth work?", "As of epoch 1.")

    async with database.session() as session:
        hit = await lookup(session, key_for(epoch=epoch), "How does auth work?")
    assert hit is not None

    async with database.session() as session:
        new_epoch = await bump_epoch(session, "payments", "api", commit="abc123")
    assert new_epoch == epoch + 1

    async with database.session() as session:
        assert await lookup(session, key_for(epoch=new_epoch), "How does auth work?") is None


async def test_an_unindexed_project_reports_epoch_zero(database):
    async with database.session() as session:
        assert await current_epoch(session, "payments", "never-indexed") == 0


async def test_the_sweep_drops_superseded_entries_only(database):
    async with database.session() as session:
        await bump_epoch(session, "payments", "api")
    await put(database, key_for(epoch=1), "Old question?", "Old answer.")

    async with database.session() as session:
        await bump_epoch(session, "payments", "api")
    await put(database, key_for(epoch=2), "New question?", "New answer.")

    async with database.session() as session:
        removed = await purge_superseded(session)
    assert removed == 1

    async with database.session() as session:
        assert await lookup(session, key_for(epoch=2), "New question?") is not None


async def test_a_ttl_expires_an_entry(database):
    await put(database, key_for(), "How does auth work?", "It uses OIDC.")
    async with database.session() as session:
        # Nothing can be younger than zero seconds, so everything is expired.
        assert await lookup(session, key_for(), "How does auth work?", ttl_seconds=0.001) is None


async def test_purge_can_be_scoped_to_one_squad(database):
    await put(database, key_for(tenant="payments"), "Q?", "A.")
    await put(database, key_for(tenant="checkout"), "Q?", "A.")
    async with database.session() as session:
        assert await purge(session, tenant="payments") == 1
    async with database.session() as session:
        assert await lookup(session, key_for(tenant="checkout"), "Q?") is not None


# ── semantic tier ────────────────────────────────────────────────────


async def test_a_close_question_is_recalled_above_the_threshold(database):
    await put(
        database,
        key_for(),
        "How does authentication work?",
        "It uses OIDC.",
        embedding=[1.0, 0.0, 0.0],
        embedding_model="test-embed",
    )
    async with database.session() as session:
        hit = await lookup(
            session,
            key_for(),
            "How is auth handled?",
            embedding=[0.99, 0.01, 0.0],
            embedding_model="test-embed",
            threshold=0.9,
        )
    assert hit is not None
    assert hit.kind == "semantic"
    assert hit.similarity > 0.9


async def test_a_distant_question_stays_a_miss(database):
    """A fluent answer to a different question is the failure nobody notices."""
    await put(
        database,
        key_for(),
        "How does authentication work?",
        "It uses OIDC.",
        embedding=[1.0, 0.0, 0.0],
        embedding_model="test-embed",
    )
    async with database.session() as session:
        assert (
            await lookup(
                session,
                key_for(),
                "What does the billing job do?",
                embedding=[0.0, 1.0, 0.0],
                embedding_model="test-embed",
                threshold=0.9,
            )
            is None
        )


async def test_entries_from_another_embedding_model_are_not_compared(database):
    """Two models' vectors are not in the same space; a score between them lies."""
    await put(
        database,
        key_for(),
        "How does authentication work?",
        "It uses OIDC.",
        embedding=[1.0, 0.0, 0.0],
        embedding_model="model-a",
    )
    async with database.session() as session:
        assert (
            await lookup(
                session,
                key_for(),
                "How is auth handled?",
                embedding=[1.0, 0.0, 0.0],
                embedding_model="model-b",
                threshold=0.9,
            )
            is None
        )


async def test_without_an_embedding_only_the_exact_tier_runs(database):
    """An unreachable embedding model degrades the cache, it does not break it."""
    await put(
        database,
        key_for(),
        "How does authentication work?",
        "It uses OIDC.",
        embedding=[1.0, 0.0, 0.0],
        embedding_model="test-embed",
    )
    async with database.session() as session:
        assert await lookup(session, key_for(), "How is auth handled?") is None
        assert await lookup(session, key_for(), "How does authentication work?") is not None


async def test_a_hit_is_counted(database):
    await put(database, key_for(), "How does auth work?", "It uses OIDC.")
    async with database.session() as session:
        await lookup(session, key_for(), "How does auth work?")
    async with database.session() as session:
        await lookup(session, key_for(), "How does auth work?")

    from sqlalchemy import select

    from repo_mcp_common.models import AnswerCacheEntry

    async with database.read() as session:
        entry = (await session.execute(select(AnswerCacheEntry))).scalar_one()
    assert entry.hits == 2
    assert entry.last_hit_at is not None


# ── the migration chain ──────────────────────────────────────────────


async def test_the_migrations_produce_the_schema_the_models_describe(database):
    """The guard that would have caught revision one creating revision two's tables.

    Revision one originally called `Base.metadata.create_all`, so it created
    whatever the models happened to contain — including tables added later,
    which then made the next revision fail on a table that already existed.
    Comparing the migrated schema to the models catches both directions: a
    migration that forgets a table, and a migration that invents one.
    """
    from sqlalchemy import inspect

    from repo_mcp_common.models import Base

    def tables(connection) -> set[str]:
        return set(inspect(connection).get_table_names())

    async with database.connect().connect() as connection:
        present = await connection.run_sync(tables)

    expected = set(Base.metadata.tables)
    assert expected - present == set(), "the migrations do not create every model table"
    # alembic_version is the chain's own bookkeeping, not a model.
    assert present - expected - {"alembic_version"} == set(), "the migrations create extra tables"


async def test_every_model_column_exists_after_migrating(database):
    from sqlalchemy import inspect

    from repo_mcp_common.models import Base

    def columns(connection, table: str) -> set[str]:
        return {c["name"] for c in inspect(connection).get_columns(table)}

    async with database.connect().connect() as connection:
        for name, table in Base.metadata.tables.items():
            present = await connection.run_sync(columns, name)
            missing = {c.name for c in table.columns} - present
            assert not missing, f"{name} is missing {sorted(missing)} after migrating"
