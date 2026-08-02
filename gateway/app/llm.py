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
from .metrics import LLM_CALLS, LLM_DURATION
from .tenants import Tenant

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """An LLM call failed or is not configured."""


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._stale: httpx.AsyncClient | None = None

    def update(self, settings: Settings) -> None:
        """Adopt configuration an administrator changed.

        The base URL is baked into the client, so a change to it has to
        discard the old one rather than silently keep talking to the previous
        endpoint.
        """
        if settings.litellm_base_url != self._settings.litellm_base_url:
            self._stale = self._client
            self._client = None
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.smart_tools_enabled and self._settings.litellm_base_url)

    async def aclose(self) -> None:
        for client in (self._client, self._stale):
            if client is not None:
                await client.aclose()
        self._client = None
        self._stale = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.litellm_base_url.rstrip("/"),
                timeout=self._settings.litellm_timeout_s,
            )
        return self._client

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
        model = self._settings.litellm_model
        started = time.perf_counter()
        try:
            response = await self._http().post(
                "/chat/completions",
                json=payload,
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
            content = response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            LLM_CALLS.labels(model, "malformed").inc()
            raise LlmError(f"malformed LiteLLM response: {exc}") from exc
        LLM_CALLS.labels(model, "ok").inc()
        return content
