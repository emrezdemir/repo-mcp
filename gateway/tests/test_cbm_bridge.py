"""Tests for the stdio bridge.

The engine is replaced with a small Python script that speaks the same
line-delimited JSON-RPC, so these cover the framing, the handshake, timeout
recovery and failure reporting without needing the real binary.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.cbm import CbmError, CbmPool, CbmSession
from app.config import Settings
from app.tenants import TenantRegistry

FAKE_ENGINE = r'''
import json, sys, time

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue                      # notification
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}}
    elif method == "tools/list":
        result = {"tools": [{"name": "search_graph"}, {"name": "list_projects"}]}
    elif method == "tools/call":
        name = message["params"]["name"]
        if name == "explode":
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -1, "message": "boom"}}), flush=True)
            continue
        if name == "hang":
            time.sleep(30)
        result = {"content": [{"type": "text", "text": f"called {name}"}],
                  "isError": name == "failing"}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''


def make_settings(tmp_path: Path, binary: str, call_timeout: float = 10.0) -> Settings:
    return Settings(
        oidc_issuer="",
        oidc_audience="repo-mcp",
        oidc_groups_claim="groups",
        dev_insecure_auth=True,
        dev_static_token="t",
        dev_static_groups=(),
        cbm_binary=binary,
        cbm_cache_root=tmp_path / "cache",
        cbm_repo_root=tmp_path / "repos",
        cbm_idle_timeout_s=900.0,
        cbm_call_timeout_s=call_timeout,
        litellm_base_url="",
        litellm_api_key="",
        litellm_model="test",
        litellm_timeout_s=30.0,
        smart_tools_enabled=False,
        answer_cache_enabled=False,
        answer_cache_embedding_model="",
        answer_cache_threshold=0.95,
        answer_cache_ttl_s=604800.0,
    )


@pytest.fixture
def tenant():
    registry = TenantRegistry.from_dict(
        {"tenants": {"acme": {"ldap_groups": ["g"], "tool_profile": "analysis",
                              "projects": ["*"]}}}
    )
    return registry.by_name("acme")


@pytest.fixture
def fake_engine(tmp_path: Path) -> str:
    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    launcher = tmp_path / "fake-engine"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    return str(launcher)


@pytest.mark.asyncio
async def test_handshake_and_tool_call(tmp_path, tenant, fake_engine):
    session = CbmSession(make_settings(tmp_path, fake_engine), tenant)
    try:
        tools = await session.list_tools()
        assert [t["name"] for t in tools] == ["search_graph", "list_projects"]

        result = await session.call_tool("search_graph", {"project": "x"})
        assert result.text() == "called search_graph"
        assert result.is_error is False
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_tool_error_flag_is_propagated(tmp_path, tenant, fake_engine):
    session = CbmSession(make_settings(tmp_path, fake_engine), tenant)
    try:
        result = await session.call_tool("failing", {})
        assert result.is_error is True
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_jsonrpc_error_becomes_cbm_error(tmp_path, tenant, fake_engine):
    session = CbmSession(make_settings(tmp_path, fake_engine), tenant)
    try:
        with pytest.raises(CbmError, match="boom"):
            await session.call_tool("explode", {})
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_missing_binary_is_reported_clearly(tmp_path, tenant):
    """A deployment problem should name itself, not surface as an HTTP 500."""
    session = CbmSession(make_settings(tmp_path, "/nonexistent/engine"), tenant)
    with pytest.raises(CbmError, match="engine binary not found"):
        await session.list_tools()


@pytest.mark.asyncio
async def test_timeout_tears_down_the_process(tmp_path, tenant, fake_engine):
    """A late reply must not be mistaken for the next call's result."""
    session = CbmSession(make_settings(tmp_path, fake_engine, call_timeout=1.0), tenant)
    try:
        with pytest.raises(CbmError, match="timed out"):
            await session.call_tool("hang", {})
        # The process is gone, so the next call starts a fresh one and works.
        result = await session.call_tool("search_graph", {})
        assert result.text() == "called search_graph"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_calls_are_serialised_over_one_stream(tmp_path, tenant, fake_engine):
    """Concurrent callers must not interleave on the single stdio stream."""
    session = CbmSession(make_settings(tmp_path, fake_engine), tenant)
    try:
        names = [f"tool{i}" for i in range(10)]
        results = await asyncio.gather(*(session.call_tool(n, {}) for n in names))
        assert sorted(r.text() for r in results) == sorted(f"called {n}" for n in names)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_pool_reuses_one_session_per_tenant(tmp_path, tenant, fake_engine):
    pool = CbmPool(make_settings(tmp_path, fake_engine))
    try:
        first = await pool.session(tenant)
        second = await pool.session(tenant)
        assert first is second
    finally:
        await pool.aclose()


@pytest.mark.asyncio
async def test_environment_isolates_tenants(tmp_path, tenant, fake_engine):
    session = CbmSession(make_settings(tmp_path, fake_engine), tenant)
    env = session._env()
    assert env["CBM_CACHE_DIR"].endswith("/cache/tenant/acme")
    assert env["CBM_ALLOWED_ROOT"].endswith("/repos/acme")
