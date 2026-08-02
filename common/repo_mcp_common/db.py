"""Async engine and session management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .env import DatabaseEnv, database_env

log = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached."""


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, env: DatabaseEnv | None = None) -> None:
        self.env = env or database_env()
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker[AsyncSession] | None = None

    # ── lifecycle ────────────────────────────────────────────────────

    def connect(self) -> AsyncEngine:
        if self._engine is not None:
            return self._engine

        kwargs: dict = {"echo": False, "future": True}
        if not self.env.is_sqlite:
            kwargs.update(
                pool_size=self.env.pool_size,
                max_overflow=self.env.pool_max_overflow,
                # Recycle before a typical cloud provider's idle timeout, and
                # check liveness rather than handing out a dead connection.
                pool_recycle=1800,
                pool_pre_ping=True,
            )
        self._engine = create_async_engine(self.env.url, **kwargs)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        return self._engine

    async def wait_until_ready(self, timeout: float | None = None) -> None:
        """Retry until the database answers, or give up with a clear message.

        The bundled database usually needs a few seconds after the service
        container starts, and crash-looping on that is noise rather than
        signal.
        """
        self.connect()
        deadline = timeout if timeout is not None else self.env.connect_retry_seconds
        waited = 0.0
        delay = 0.5
        last: Exception | None = None

        while waited <= deadline:
            try:
                async with self._engine.connect() as connection:  # type: ignore[union-attr]
                    await connection.execute(text("SELECT 1"))
                if waited:
                    log.info("database reachable after %.1fs", waited)
                return
            except (SQLAlchemyError, OSError) as exc:
                last = exc
                await asyncio.sleep(delay)
                waited += delay
                delay = min(delay * 2, 5.0)

        raise DatabaseUnavailable(
            f"cannot reach the database at {self.env.redacted_url()} after "
            f"{deadline:.0f}s: {last}"
        )

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessions = None

    # ── sessions ─────────────────────────────────────────────────────

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session that commits on success and rolls back on failure."""
        if self._sessions is None:
            self.connect()
        assert self._sessions is not None
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        """A read-only session; never commits."""
        if self._sessions is None:
            self.connect()
        assert self._sessions is not None
        async with self._sessions() as session:
            yield session
