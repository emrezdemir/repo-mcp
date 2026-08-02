"""LiteLLM proxy client.

The engine has no LLM inside it and its embeddings are compiled into the binary, so
nothing can be routed through LiteLLM *underneath* the engine (see
docs/engine.md). The reasoning layer therefore sits *above* it.

Because everything goes through LiteLLM, self-hosted backends — Ollama, vLLM,
llama.cpp — are a proxy configuration concern rather than a change here.

Each request carries the squad's virtual key, so budgets, rate limits and
prompt logs are already separated per squad on the LiteLLM side.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from .config import Settings
from .metrics import COMPRESSION_FALLBACKS, LLM_CALLS, LLM_DURATION
from .tenants import Tenant

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """An LLM call failed or is not configured."""


class LlmUnreachable(LlmError):
    """The endpoint could not be reached, or answered with a server error.

    Separate from `LlmError` because it is the only failure worth retrying
    elsewhere: a 400 from the model means the same thing on every route.
    """


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        #: One client per base URL. Chat completions may go through the
        #: compression proxy while embeddings go straight to LiteLLM, so there
        #: is more than one endpoint in play.
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._stale: list[httpx.AsyncClient] = []

    def update(self, settings: Settings) -> None:
        """Adopt configuration an administrator changed.

        A base URL is baked into its client, so a change has to discard the old
        one rather than silently keep talking to the previous endpoint.
        """
        live = {
            settings.litellm_base_url.rstrip("/"),
            settings.headroom_base_url.rstrip("/"),
        }
        for url in [u for u in self._clients if u not in live]:
            self._stale.append(self._clients.pop(url))
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.smart_tools_enabled and self._settings.litellm_base_url)

    async def aclose(self) -> None:
        for client in [*self._clients.values(), *self._stale]:
            await client.aclose()
        self._clients.clear()
        self._stale.clear()

    def _http(self, base_url: str) -> httpx.AsyncClient:
        url = base_url.rstrip("/")
        if url not in self._clients:
            self._clients[url] = httpx.AsyncClient(
                base_url=url, timeout=self._settings.litellm_timeout_s
            )
        return self._clients[url]

    def _chat_route(self) -> str | None:
        """The compression proxy, when an administrator turned it on.

        Embeddings deliberately do not use it: compressing the text first would
        move the vector, and the answer cache keys on that vector.
        See docs/adr/0010-headroom-plugin.md.
        """
        if not self._settings.headroom_enabled:
            return None
        return self._settings.headroom_base_url.rstrip("/") or None

    def _api_key(self, tenant: Tenant) -> str:
        if tenant.litellm_key_env:
            key = os.getenv(tenant.litellm_key_env)
            if not key:
                raise LlmError(
                    f"tenant {tenant.name!r} expects {tenant.litellm_key_env} to be set"
                )
            return key
        if not self._settings.litellm_api_key:
            raise LlmError("LITELLM_API_KEY is not set")
        return self._settings.litellm_api_key

    async def complete(
        self,
        *,
        tenant: Tenant,
        username: str,
        system: str,
        user: str,
        max_tokens: int = 1500,
    ) -> str:
        if not self.enabled:
            raise LlmError("smart tools are disabled (SMART_TOOLS_ENABLED/LITELLM_BASE_URL)")
        payload = {
            "model": self._settings.litellm_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Attribution for LiteLLM's usage reporting: who, and which squad.
            "user": username,
            "metadata": {"tags": [f"squad:{tenant.name}"]},
        }
        headers = {"Authorization": f"Bearer {self._api_key(tenant)}"}
        route = self._chat_route()

        if route is not None:
            try:
                return await self._chat(route, payload, headers)
            except LlmUnreachable as exc:
                if not self._settings.headroom_fallback:
                    raise
                # The caller asked a question about a codebase; whether a
                # compression proxy was involved is the operator's concern,
                # not theirs. Loud here, invisible there.
                log.warning("compression proxy unavailable, answering directly: %s", exc)
                COMPRESSION_FALLBACKS.inc()

        return await self._chat(self._settings.litellm_base_url, payload, headers)

    async def _chat(self, base_url: str, payload: dict, headers: dict) -> str:
        model = str(payload["model"])
        started = time.perf_counter()
        try:
            response = await self._http(base_url).post(
                "/chat/completions", json=payload, headers=headers
            )
        except httpx.HTTPError as exc:
            LLM_CALLS.labels(model, "unreachable").inc()
            raise LlmUnreachable(f"cannot reach {base_url}: {exc}") from exc
        finally:
            LLM_DURATION.labels(model).observe(time.perf_counter() - started)

        if response.status_code >= 500:
            LLM_CALLS.labels(model, "http_5xx").inc()
            raise LlmUnreachable(f"{base_url} returned {response.status_code}")
        if response.status_code >= 400:
            LLM_CALLS.labels(model, f"http_{response.status_code // 100}xx").inc()
            raise LlmError(f"{base_url} returned {response.status_code}: {response.text[:500]}")
        try:
            content = response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            LLM_CALLS.labels(model, "malformed").inc()
            raise LlmError(f"malformed response from {base_url}: {exc}") from exc
        LLM_CALLS.labels(model, "ok").inc()
        return content

    async def embed(self, *, tenant: Tenant, username: str, text: str, model: str) -> list[float]:
        """One embedding, through the same proxy and the same squad key.

        The engine's own embeddings are compiled into its binary and cannot be
        reached, so the answer cache uses this instead (docs/engine.md,
        docs/adr/0009-answer-cache.md).
        """
        if not self._settings.litellm_base_url:
            raise LlmError("LITELLM_BASE_URL is not set")
        if not model:
            raise LlmError("no embedding model is configured (answer_cache.embedding_model)")

        started = time.perf_counter()
        try:
            # Straight to LiteLLM, never through the compression proxy.
            response = await self._http(self._settings.litellm_base_url).post(
                "/embeddings",
                json={"model": model, "input": text, "user": username},
                headers={"Authorization": f"Bearer {self._api_key(tenant)}"},
            )
        except httpx.HTTPError as exc:
            LLM_CALLS.labels(model, "unreachable").inc()
            raise LlmError(f"cannot reach LiteLLM: {exc}") from exc
        finally:
            LLM_DURATION.labels(model).observe(time.perf_counter() - started)

        if response.status_code >= 400:
            LLM_CALLS.labels(model, f"http_{response.status_code // 100}xx").inc()
            raise LlmError(f"LiteLLM returned {response.status_code}: {response.text[:500]}")
        try:
            vector = response.json()["data"][0]["embedding"]
        except (KeyError, IndexError, ValueError) as exc:
            LLM_CALLS.labels(model, "malformed").inc()
            raise LlmError(f"malformed embedding response: {exc}") from exc
        if not isinstance(vector, list) or not vector:
            LLM_CALLS.labels(model, "malformed").inc()
            raise LlmError("embedding response carried no vector")
        LLM_CALLS.labels(model, "ok").inc()
        return [float(x) for x in vector]
