"""Where a chat completion is sent, and what happens when that endpoint is down.

The compression proxy sits between the gateway and LiteLLM
(docs/adr/0010-headroom-plugin.md). Three properties matter: it is used when
an administrator turns it on, it never sees an embedding, and it cannot take
down question-answering by being unavailable.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.llm import LlmClient, LlmError
from app.tenants import Tenant


def settings(**overrides) -> Settings:
    base = Settings(
        oidc_issuer="",
        oidc_audience="repo-mcp",
        oidc_groups_claim="groups",
        dev_insecure_auth=True,
        dev_static_token="t",
        dev_static_groups=(),
        cbm_binary="cbm",
        cbm_cache_root=Path("/tmp/cache"),
        cbm_repo_root=Path("/tmp/repos"),
        cbm_idle_timeout_s=900,
        cbm_call_timeout_s=120,
        litellm_base_url="http://litellm",
        litellm_api_key="key",
        litellm_model="test-model",
        litellm_timeout_s=10,
        smart_tools_enabled=True,
        answer_cache_enabled=False,
        answer_cache_embedding_model="",
        answer_cache_threshold=0.95,
        answer_cache_ttl_s=604800.0,
        headroom_enabled=False,
        headroom_base_url="",
        headroom_fallback=True,
    )
    return replace(base, **overrides)


def tenant() -> Tenant:
    return Tenant(
        name="payments",
        ldap_groups=frozenset({"squad-payments"}),
        projects=("*",),
        tool_profile="analysis",
        structural_only=False,
        denied_tools=frozenset(),
        litellm_key_env="",
    )


def wire(client: LlmClient, handler) -> None:
    """Give every route a transport that records where the request went."""
    original = client._http

    def patched(base_url: str) -> httpx.AsyncClient:
        http = original(base_url)
        http._transport = httpx.MockTransport(handler)
        return http

    client._http = patched  # type: ignore[method-assign]


def recorder(seen: list[str], response=None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return response or httpx.Response(200, json=completion())

    return handler


def completion(text: str = "an answer") -> dict:
    return {"choices": [{"message": {"content": text}}]}


async def ask(client: LlmClient) -> str:
    return await client.complete(tenant=tenant(), username="dev", system="s", user="u")


def with_proxy(**overrides) -> Settings:
    return settings(
        headroom_enabled=True, headroom_base_url="http://headroom:8787/v1", **overrides
    )


async def test_without_the_proxy_a_completion_goes_straight_to_litellm():
    seen: list[str] = []
    client = LlmClient(settings())
    wire(client, recorder(seen))
    assert await ask(client) == "an answer"
    assert seen == ["http://litellm/chat/completions"]
    await client.aclose()


async def test_the_proxy_is_used_when_an_administrator_enables_it():
    seen: list[str] = []
    client = LlmClient(with_proxy())
    wire(client, recorder(seen))
    await ask(client)
    assert seen == ["http://headroom:8787/v1/chat/completions"]
    await client.aclose()


async def test_a_configured_but_disabled_proxy_is_not_used():
    """Turning it off must need nothing but the one setting."""
    seen: list[str] = []
    client = LlmClient(settings(headroom_base_url="http://headroom:8787/v1"))
    wire(client, recorder(seen))
    await ask(client)
    assert seen == ["http://litellm/chat/completions"]
    await client.aclose()


async def test_an_unreachable_proxy_falls_back_rather_than_failing():
    """A compression layer must not be able to take down answering."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "headroom" in str(request.url):
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=completion())

    client = LlmClient(with_proxy())
    wire(client, handler)
    assert await ask(client) == "an answer"
    assert seen == [
        "http://headroom:8787/v1/chat/completions",
        "http://litellm/chat/completions",
    ]
    await client.aclose()


async def test_a_server_error_from_the_proxy_also_falls_back():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "headroom" in str(request.url):
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json=completion())

    client = LlmClient(with_proxy())
    wire(client, handler)
    assert await ask(client) == "an answer"
    assert len(seen) == 2
    await client.aclose()


async def test_a_rejected_request_is_not_retried_elsewhere():
    """A 400 means the same thing on every route; retrying only hides it."""
    seen: list[str] = []
    client = LlmClient(with_proxy())
    wire(client, recorder(seen, httpx.Response(400, text="bad request")))
    with pytest.raises(LlmError):
        await ask(client)
    assert len(seen) == 1
    await client.aclose()


async def test_fallback_can_be_refused():
    """An operator who wants compression or nothing can say so."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = LlmClient(with_proxy(headroom_fallback=False))
    wire(client, handler)
    with pytest.raises(LlmError):
        await ask(client)
    await client.aclose()


async def test_an_embedding_never_goes_through_the_proxy():
    """Compressing the text would move the vector the answer cache keys on."""
    seen: list[str] = []
    client = LlmClient(with_proxy())
    wire(client, recorder(seen, httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})))
    vector = await client.embed(
        tenant=tenant(), username="dev", text="how does auth work", model="embed-model"
    )
    assert vector == pytest.approx([0.1, 0.2])
    assert seen == ["http://litellm/embeddings"]
    await client.aclose()


async def test_changing_the_base_url_discards_the_old_client():
    client = LlmClient(settings())
    client._http("http://litellm")
    assert "http://litellm" in client._clients
    client.update(settings(litellm_base_url="http://elsewhere"))
    assert "http://litellm" not in client._clients
    await client.aclose()
