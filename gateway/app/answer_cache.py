"""The answer cache, as the request path sees it.

`repo_mcp_common.answer_cache` holds the storage and the scoring. This adds
what only the gateway knows: the settings an administrator changed, the
squad's embedding call, the metrics, and the rule about which tools may be
cached at all.

Every failure here is swallowed. A cache is an optimisation, and an
optimisation that can fail a request is a liability — a broken cache must cost
tokens, not answers. See docs/adr/0009-answer-cache.md.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from repo_mcp_common import answer_cache as store
from repo_mcp_common.db import Database

from .config import Settings
from .llm import LlmClient, LlmError
from .metrics import CACHE_LOOKUP_SECONDS, CACHE_LOOKUPS
from .tenants import Tenant

log = logging.getLogger(__name__)

#: Which composite tools may be cached, and what counts as the question.
#:
#: `explain_change_impact` is absent on purpose: its answer depends on the
#: working tree as well as the graph, and the cache key describes only the
#: graph. Caching it would return an impact set for a diff that has changed.
CACHEABLE: dict[str, Callable[[dict], str]] = {
    "ask_codebase": lambda args: str(args.get("question") or ""),
}


class AnswerCache:
    def __init__(self, database: Database, llm: LlmClient) -> None:
        self._db = database
        self._llm = llm

    def applies(self, settings: Settings, tool: str, args: dict) -> bool:
        return bool(
            settings.answer_cache_enabled
            and tool in CACHEABLE
            and CACHEABLE[tool](args).strip()
            and args.get("project")
        )

    async def lookup(
        self, *, settings: Settings, tenant: Tenant, username: str, tool: str, args: dict
    ) -> store.CacheHit | None:
        if not self.applies(settings, tool, args):
            return None

        question = CACHEABLE[tool](args)
        project = str(args["project"])
        started = time.perf_counter()
        try:
            async with self._db.session() as session:
                key = store.CacheKey(
                    tenant=tenant.name,
                    project=project,
                    tool=tool,
                    epoch=await store.current_epoch(session, tenant.name, project),
                )
                # The exact tier first, with no embedding: the common repeat
                # should not cost a network call to find out it is a repeat.
                hit = await store.lookup(
                    session,
                    key,
                    question,
                    threshold=settings.answer_cache_threshold,
                    ttl_seconds=settings.answer_cache_ttl_s,
                )
                if hit is None and settings.answer_cache_embedding_model:
                    embedding = await self._embed(settings, tenant, username, question)
                    if embedding is not None:
                        hit = await store.lookup(
                            session,
                            key,
                            question,
                            embedding=embedding,
                            embedding_model=settings.answer_cache_embedding_model,
                            threshold=settings.answer_cache_threshold,
                            ttl_seconds=settings.answer_cache_ttl_s,
                        )
        except Exception:  # noqa: BLE001 - a cache must never fail a request
            log.warning("answer cache lookup failed; answering from the model", exc_info=True)
            CACHE_LOOKUPS.labels(tool, "error").inc()
            return None
        finally:
            CACHE_LOOKUP_SECONDS.labels(tool).observe(time.perf_counter() - started)

        CACHE_LOOKUPS.labels(tool, hit.kind if hit else "miss").inc()
        return hit

    async def store(
        self,
        *,
        settings: Settings,
        tenant: Tenant,
        username: str,
        tool: str,
        args: dict,
        answer: str,
    ) -> None:
        if not self.applies(settings, tool, args) or not answer.strip():
            return

        question = CACHEABLE[tool](args)
        project = str(args["project"])
        try:
            embedding = None
            if settings.answer_cache_embedding_model:
                embedding = await self._embed(settings, tenant, username, question)
            async with self._db.session() as session:
                key = store.CacheKey(
                    tenant=tenant.name,
                    project=project,
                    tool=tool,
                    epoch=await store.current_epoch(session, tenant.name, project),
                )
                await store.store(
                    session,
                    key,
                    question,
                    answer,
                    answer_model=settings.litellm_model,
                    embedding=embedding,
                    embedding_model=(
                        settings.answer_cache_embedding_model if embedding else None
                    ),
                )
        except Exception:  # noqa: BLE001 - the answer is already correct
            log.warning("answer cache store failed; the answer was returned", exc_info=True)

    async def _embed(
        self, settings: Settings, tenant: Tenant, username: str, question: str
    ) -> list[float] | None:
        """Embed the question, or give up quietly.

        An unreachable embedding model must degrade to an exact-match-only
        cache, not to a failed tool call.
        """
        try:
            return await self._llm.embed(
                tenant=tenant,
                username=username,
                text=store.normalise(question),
                model=settings.answer_cache_embedding_model,
            )
        except LlmError as exc:
            log.warning("embedding unavailable, semantic cache lookup skipped: %s", exc)
            return None
