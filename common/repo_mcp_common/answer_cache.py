"""Per-squad cache of LLM answers.

Two tiers. An exact hash of the normalised question is looked up first and
costs one indexed read; only a miss pays for an embedding and a similarity
scan over the candidate set for that squad, project, tool and graph epoch.

The epoch is what makes invalidation exact: a reindex bumps it, and every
answer computed from the previous graph stops being a candidate at once.
Nothing in an answer's text says whether it is stale, which is why this is not
a TTL. See docs/adr/0009-answer-cache.md.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnswerCacheEntry, ProjectIndexState

log = logging.getLogger(__name__)

#: Upper bound on the rows scored for one lookup. Beyond this the design is
#: past what ADR-0009 signed up for, and the ADR names pgvector as the answer.
CANDIDATE_LIMIT = 5000

_WHITESPACE = re.compile(r"\s+")


def normalise(question: str) -> str:
    """Fold the differences that never change what is being asked.

    Case and whitespace only. Deliberately not stemming or stop-word removal:
    "does this call X" and "does X call this" must not collapse.
    """
    return _WHITESPACE.sub(" ", question.strip().lower())


def question_hash(question: str) -> str:
    return hashlib.sha256(normalise(question).encode("utf-8")).hexdigest()


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity, or 0.0 when either vector has no direction."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass(frozen=True)
class CacheKey:
    """Everything that has to match for a cached answer to still apply."""

    tenant: str
    project: str
    tool: str
    epoch: int


@dataclass(frozen=True)
class CacheHit:
    answer: str
    #: "exact" or "semantic" — reported in metrics and in the tool's own
    #: response, so a developer can tell a recalled answer from a fresh one.
    kind: str
    similarity: float
    age_seconds: float


# ── epochs ───────────────────────────────────────────────────────────


async def current_epoch(session: AsyncSession, tenant: str, project: str) -> int:
    """The project's graph epoch. Zero when it has never been indexed here.

    Zero is a usable key: answers cached before the first recorded index are
    retired by the first one, which is the conservative direction.
    """
    row = await session.get(ProjectIndexState, (tenant, project))
    return row.epoch if row is not None else 0


async def bump_epoch(
    session: AsyncSession, tenant: str, project: str, *, commit: str | None = None
) -> int:
    """Record that a project's graph changed. Called after a successful index."""
    row = await session.get(ProjectIndexState, (tenant, project))
    if row is None:
        row = ProjectIndexState(tenant=tenant, project=project, epoch=1, last_commit=commit)
        session.add(row)
        return 1
    row.epoch += 1
    row.last_commit = commit or row.last_commit
    row.last_indexed_at = datetime.now(UTC)
    return row.epoch


# ── lookup and store ─────────────────────────────────────────────────


async def lookup(
    session: AsyncSession,
    key: CacheKey,
    question: str,
    *,
    embedding: list[float] | None = None,
    embedding_model: str | None = None,
    threshold: float = 0.95,
    ttl_seconds: float = 0.0,
) -> CacheHit | None:
    """Find a usable cached answer, exact match first.

    A hit updates the entry's counters, so an operator can see which questions
    a squad actually repeats.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None

    exact = (
        await session.execute(
            select(AnswerCacheEntry).where(
                AnswerCacheEntry.tenant == key.tenant,
                AnswerCacheEntry.project == key.project,
                AnswerCacheEntry.tool == key.tool,
                AnswerCacheEntry.epoch == key.epoch,
                AnswerCacheEntry.question_hash == question_hash(question),
            )
        )
    ).scalar_one_or_none()

    if exact is not None and (cutoff is None or _aware(exact.created_at) >= cutoff):
        await _record_hit(session, exact, now)
        return CacheHit(
            answer=exact.answer,
            kind="exact",
            similarity=1.0,
            age_seconds=(now - _aware(exact.created_at)).total_seconds(),
        )

    if embedding is None or not embedding_model:
        return None

    # Only entries embedded by the same model are comparable: vectors from two
    # models are not in the same space, and a similarity between them is a
    # number with no meaning.
    candidates = (
        (
            await session.execute(
                select(AnswerCacheEntry)
                .where(
                    AnswerCacheEntry.tenant == key.tenant,
                    AnswerCacheEntry.project == key.project,
                    AnswerCacheEntry.tool == key.tool,
                    AnswerCacheEntry.epoch == key.epoch,
                    AnswerCacheEntry.embedding_model == embedding_model,
                    AnswerCacheEntry.embedding_dim == len(embedding),
                    AnswerCacheEntry.embedding.is_not(None),
                )
                .order_by(AnswerCacheEntry.created_at.desc())
                .limit(CANDIDATE_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    best: AnswerCacheEntry | None = None
    best_score = 0.0
    for entry in candidates:
        if cutoff is not None and _aware(entry.created_at) < cutoff:
            continue
        score = cosine(embedding, unpack(entry.embedding or b""))
        if score > best_score:
            best, best_score = entry, score

    if best is None or best_score < threshold:
        return None

    await _record_hit(session, best, now)
    return CacheHit(
        answer=best.answer,
        kind="semantic",
        similarity=best_score,
        age_seconds=(now - _aware(best.created_at)).total_seconds(),
    )


async def store(
    session: AsyncSession,
    key: CacheKey,
    question: str,
    answer: str,
    *,
    answer_model: str,
    embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> None:
    """Record an answer, replacing any entry with the same exact key.

    Replacing rather than skipping keeps the unique constraint honest when two
    replicas answer the same question at the same moment.
    """
    digest = question_hash(question)
    await session.execute(
        delete(AnswerCacheEntry).where(
            AnswerCacheEntry.tenant == key.tenant,
            AnswerCacheEntry.project == key.project,
            AnswerCacheEntry.tool == key.tool,
            AnswerCacheEntry.epoch == key.epoch,
            AnswerCacheEntry.question_hash == digest,
        )
    )
    session.add(
        AnswerCacheEntry(
            tenant=key.tenant,
            project=key.project,
            tool=key.tool,
            epoch=key.epoch,
            question_hash=digest,
            question=question,
            answer=answer,
            answer_model=answer_model,
            embedding_model=embedding_model,
            embedding=pack(embedding) if embedding else None,
            embedding_dim=len(embedding) if embedding else 0,
        )
    )


async def purge(
    session: AsyncSession,
    *,
    tenant: str | None = None,
    project: str | None = None,
    older_than_seconds: float | None = None,
) -> int:
    """Drop entries. Used by the admin API and by the periodic sweep.

    Superseded epochs are dropped by the sweep rather than at bump time: the
    bump happens on the indexing path, and a delete of unknown size does not
    belong there.
    """
    statement = delete(AnswerCacheEntry)
    if tenant:
        statement = statement.where(AnswerCacheEntry.tenant == tenant)
    if project:
        statement = statement.where(AnswerCacheEntry.project == project)
    if older_than_seconds is not None:
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        statement = statement.where(AnswerCacheEntry.created_at < cutoff)
    result = await session.execute(statement)
    return result.rowcount or 0


async def purge_superseded(session: AsyncSession) -> int:
    """Drop entries whose project has since been reindexed."""
    states = (await session.execute(select(ProjectIndexState))).scalars().all()
    removed = 0
    for state in states:
        result = await session.execute(
            delete(AnswerCacheEntry).where(
                AnswerCacheEntry.tenant == state.tenant,
                AnswerCacheEntry.project == state.project,
                AnswerCacheEntry.epoch < state.epoch,
            )
        )
        removed += result.rowcount or 0
    return removed


async def stats(session: AsyncSession) -> dict:
    """A small summary for the admin API: what is cached, and how often it lands."""
    rows = (
        await session.execute(
            select(
                AnswerCacheEntry.tenant,
                AnswerCacheEntry.project,
                AnswerCacheEntry.tool,
            ).limit(CANDIDATE_LIMIT)
        )
    ).all()
    hits = (await session.execute(select(AnswerCacheEntry.hits))).scalars().all()
    return {
        "entries": len(rows),
        "hits": sum(hits),
        "squads": sorted({row[0] for row in rows}),
    }


async def _record_hit(session: AsyncSession, entry: AnswerCacheEntry, now: datetime) -> None:
    await session.execute(
        update(AnswerCacheEntry)
        .where(AnswerCacheEntry.id == entry.id)
        .values(hits=AnswerCacheEntry.hits + 1, last_hit_at=now)
    )


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; PostgreSQL does not."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
