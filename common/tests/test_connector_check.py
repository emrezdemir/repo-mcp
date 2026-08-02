"""The connector check.

What matters here is not that discovery works — that is the provider's job and
indexer/tests covers the parsing — but that every way it can go wrong comes
back as a sentence naming what to change. A check that says "HTTPStatusError"
has moved the problem rather than solved it.
"""

from __future__ import annotations

import httpx
import pytest

from repo_mcp_common import connector_check
from repo_mcp_common.connector_check import check_connector
from repo_mcp_common.providers import DiscoveredRepo, selected


class FakeProvider:
    """Yields what it was given, or raises what it was given."""

    name = "fake"

    def __init__(self, repos=(), error: Exception | None = None) -> None:
        self._repos = repos
        self._error = error

    async def discover(self):
        if self._error is not None:
            raise self._error
        for repo in self._repos:
            yield repo


def repo(full_name: str, **kwargs) -> DiscoveredRepo:
    return DiscoveredRepo(
        full_name=full_name,
        clone_url=f"https://example.com/{full_name}.git",
        default_branch="main",
        **kwargs,
    )


def install(monkeypatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(connector_check, "build_provider", lambda *a, **k: provider)


def status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/orgs/acme/repos")
    return httpx.HTTPStatusError(
        f"{code}", request=request, response=httpx.Response(code, request=request)
    )


# ── the patterns ─────────────────────────────────────────────────────


def test_a_pattern_matches_the_qualified_name_or_the_last_segment():
    assert selected("acme/payments-api", ["payments-*"], [])
    assert selected("acme/payments-api", ["acme/*"], [])
    assert not selected("acme/payments-api", ["billing-*"], [])


def test_exclude_beats_include():
    assert not selected("acme/payments-legacy", ["payments-*"], ["*-legacy"])


# ── what it reports ──────────────────────────────────────────────────


async def test_it_counts_what_the_patterns_keep(monkeypatch):
    install(monkeypatch, FakeProvider([
        repo("acme/payments-api"),
        repo("acme/payments-web"),
        repo("acme/payments-legacy"),
        repo("acme/billing"),
    ]))

    result = await check_connector(
        provider="github", settings={"org": "acme"}, token="t",
        include=["payments-*"], exclude=["*-legacy"],
    )

    assert result.ok
    assert result.discovered == 4
    assert result.matched == 2
    assert result.sample == ("acme/payments-api", "acme/payments-web")
    # Named, not merely counted: a pattern that quietly drops the repository
    # someone was looking for is the failure this exists to make visible.
    assert "acme/payments-legacy" in result.excluded


async def test_archived_and_empty_are_reported_separately(monkeypatch):
    install(monkeypatch, FakeProvider([
        repo("acme/live"),
        repo("acme/old", archived=True),
        repo("acme/blank", empty=True),
    ]))

    result = await check_connector(provider="github", settings={"org": "acme"}, token="t")

    assert result.ok
    assert (result.matched, result.skipped) == (1, 2)


async def test_patterns_that_keep_nothing_say_which_patterns(monkeypatch):
    install(monkeypatch, FakeProvider([repo("acme/billing")]))

    result = await check_connector(
        provider="github", settings={"org": "acme"}, token="t", include=["payments-*"],
    )

    assert not result.ok
    assert "payments-*" in result.reason
    assert result.discovered == 1


async def test_an_empty_organisation_is_not_reported_as_success(monkeypatch):
    install(monkeypatch, FakeProvider([]))

    result = await check_connector(provider="github", settings={"org": "acme"}, token="t")

    assert not result.ok
    assert "no repositories" in result.reason


async def test_it_stops_at_the_limit_and_says_so(monkeypatch):
    install(monkeypatch, FakeProvider([repo(f"acme/r{n}") for n in range(50)]))

    result = await check_connector(
        provider="github", settings={"org": "acme"}, token="t", limit=10,
    )

    assert result.ok
    assert result.truncated
    assert result.discovered == 10


# ── how it fails ─────────────────────────────────────────────────────


async def test_a_missing_token_names_what_to_do():
    result = await check_connector(provider="github", settings={"org": "acme"}, token=None)

    assert not result.ok
    assert "secret" in result.reason


async def test_a_missing_provider_setting_names_the_setting():
    result = await check_connector(provider="github", settings={}, token="t")

    assert not result.ok
    assert "org" in result.reason


async def test_an_unknown_provider_is_refused():
    result = await check_connector(provider="perforce", settings={}, token="t")

    assert not result.ok
    assert "perforce" in result.reason


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, "token was refused"),
        (403, "token was refused"),
        (404, "no such organisation"),
        (429, "rate-limiting"),
        (503, "their side"),
    ],
)
async def test_a_provider_refusal_becomes_a_sentence(monkeypatch, code, expected):
    install(monkeypatch, FakeProvider(error=status_error(code)))

    result = await check_connector(provider="github", settings={"org": "acme"}, token="t")

    assert not result.ok
    assert expected in result.reason


async def test_the_container_is_named_the_way_the_provider_names_it(monkeypatch):
    install(monkeypatch, FakeProvider(error=status_error(404)))

    gitlab = await check_connector(provider="gitlab", settings={"group": "acme"}, token="t")
    bitbucket = await check_connector(
        provider="bitbucket", settings={"workspace": "acme", "username": "bot"}, token="t"
    )

    assert "group" in gitlab.reason
    assert "workspace" in bitbucket.reason


async def test_an_unreachable_provider_is_not_a_crash(monkeypatch):
    install(monkeypatch, FakeProvider(error=httpx.ConnectError("nope")))

    result = await check_connector(provider="github", settings={"org": "acme"}, token="t")

    assert not result.ok
    assert "could not reach" in result.reason


async def test_a_provider_that_never_answers_gives_up(monkeypatch):
    import asyncio

    class Hangs(FakeProvider):
        async def discover(self):
            await asyncio.sleep(10)
            yield  # pragma: no cover

    install(monkeypatch, Hangs())

    result = await check_connector(
        provider="github", settings={"org": "acme"}, token="t", timeout=0.05,
    )

    assert not result.ok
    assert "did not answer" in result.reason
