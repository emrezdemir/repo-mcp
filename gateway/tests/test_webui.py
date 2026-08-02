"""Tests for the two endpoints the web interface needs, and for how it is served.

The interface has no privileged read path — every question about a codebase
goes to /mcp with the caller's own token — so there is very little here to
test, which is the point. What remains is worth pinning:

  * `/api/auth` says how to sign in, before anyone is signed in, and must not
    leak more than the redirect it describes would.
  * `/api/session` answers with what the caller may do, and refuses an
    unauthenticated caller.
  * `/ui/<path>` serves the interface and nothing outside it.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.configuration import RuntimeConfig
from app.tenants import TenantRegistry
from app.webui import UI_DIR, build_router

CONFIG = {
    "roles": {"developer": ["squad-payments"], "viewer": ["contractors"]},
    "tenants": {
        "payments": {
            "ldap_groups": ["squad-payments", "contractors"],
            "tool_profile": "analysis",
            "projects": ["payments-*"],
        },
        "platform": {
            "ldap_groups": ["squad-platform"],
            "tool_profile": "analysis",
            "projects": ["*"],
        },
    },
}


def settings(**overrides) -> Settings:
    base = Settings(
        oidc_issuer="",
        oidc_audience="repo-mcp",
        oidc_groups_claim="groups",
        dev_insecure_auth=True,
        dev_static_token="devtoken",
        dev_static_groups=("squad-payments",),
        cbm_binary="codebase-memory-mcp",
        cbm_cache_root=pathlib.Path("/var/lib/repo-mcp/cache"),
        cbm_repo_root=pathlib.Path("/var/lib/repo-mcp/repos"),
        cbm_idle_timeout_s=900.0,
        cbm_call_timeout_s=120.0,
        litellm_base_url="",
        litellm_api_key="",
        litellm_model="test",
        litellm_timeout_s=30.0,
        smart_tools_enabled=False,
        answer_cache_enabled=False,
        answer_cache_embedding_model="",
        answer_cache_threshold=0.95,
        answer_cache_ttl_s=604800.0,
        headroom_enabled=False,
        headroom_base_url="",
        headroom_fallback=True,
    )
    return replace(base, **overrides)


def client(*, ready: bool = True, **overrides) -> TestClient:
    config = RuntimeConfig(
        generation=1,
        registry=TenantRegistry.from_dict(CONFIG),
        settings=settings(**overrides),
        secrets={},
    )

    async def current():
        return config

    app = FastAPI()
    app.include_router(build_router(current, lambda: ready))
    return TestClient(app)


# ── how to sign in ───────────────────────────────────────────────────


def test_auth_reports_development_mode_plainly():
    """Anyone looking at the sign-in screen should be able to tell.

    This mode accepts one static token and verifies nothing; a screen that
    looked the same as a real one would be actively misleading.
    """
    body = client(dev_insecure_auth=True).get("/api/auth").json()
    assert body["mode"] == "development"
    assert "not verified" in body["reason"]


def test_auth_describes_the_redirect_when_a_browser_client_exists():
    body = client(
        dev_insecure_auth=False,
        oidc_issuer="https://sso.example.com/realms/acme/",
        oidc_browser_client_id="repo-mcp-web",
        oidc_browser_scopes="openid profile groups",
    ).get("/api/auth").json()

    assert body["mode"] == "oidc"
    # The trailing slash would produce a double slash in the discovery URL.
    assert body["issuer"] == "https://sso.example.com/realms/acme"
    assert body["client_id"] == "repo-mcp-web"
    assert body["scopes"] == "openid profile groups"


def test_auth_falls_back_to_the_token_box_without_a_browser_client():
    body = client(
        dev_insecure_auth=False, oidc_issuer="https://sso.example.com/realms/acme"
    ).get("/api/auth").json()

    assert body["mode"] == "token"
    assert "oidc.browser_client_id" in body["reason"]


def test_auth_carries_no_secret():
    """Everything in the answer is visible in the redirect it describes."""
    body = client(
        dev_insecure_auth=False,
        oidc_issuer="https://sso.example.com/realms/acme",
        oidc_browser_client_id="repo-mcp-web",
    ).get("/api/auth").json()

    assert set(body) == {"mode", "issuer", "client_id", "audience", "scopes"}


def test_auth_says_so_before_the_platform_is_configured():
    response = client(ready=False).get("/api/auth")
    assert response.status_code == 503


# ── who am I ─────────────────────────────────────────────────────────


def test_session_refuses_a_caller_with_no_token():
    assert client().get("/api/session").status_code == 401


def test_session_refuses_the_wrong_token():
    response = client().get("/api/session", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_session_reports_the_squad_and_what_it_allows():
    body = client().get(
        "/api/session", headers={"Authorization": "Bearer devtoken"}
    ).json()

    assert body["username"] == "dev"
    assert body["squads"] == ["payments"]
    assert body["squad"] == "payments"
    assert body["can"]["search"] is True
    assert "search_graph" in body["tools"]


def test_session_offers_the_choice_rather_than_failing_on_several_squads():
    """Belonging to two squads is not an error for this endpoint.

    The interface asks precisely so it can offer the choice; failing here
    would leave it with nothing to offer.
    """
    body = client(dev_static_groups=("squad-payments", "squad-platform")).get(
        "/api/session", headers={"Authorization": "Bearer devtoken"}
    ).json()

    assert body["squad"] is None
    assert sorted(body["squads"]) == ["payments", "platform"]
    assert body["reason"]


def test_session_honours_the_chosen_squad():
    body = client(dev_static_groups=("squad-payments", "squad-platform")).get(
        "/api/session",
        headers={"Authorization": "Bearer devtoken", "X-Tenant": "platform"},
    ).json()

    assert body["squad"] == "platform"


def test_session_tools_are_the_ones_the_role_and_the_squad_both_allow():
    """A viewer may not read source, whatever the squad's profile is."""
    body = client(dev_static_groups=("contractors",)).get(
        "/api/session", headers={"Authorization": "Bearer devtoken"}
    ).json()

    assert body["role"] == "viewer"
    assert body["can"]["read_source"] is False
    assert "get_code_snippet" not in body["tools"]


# ── serving the interface ────────────────────────────────────────────


def test_the_root_serves_the_page():
    response = client().get("/ui")
    assert response.status_code == 200
    assert "<title>repo-mcp</title>" in response.text


def test_the_built_assets_are_served():
    """The interface is a Vite build: one hashed bundle per kind, under
    assets/. A route that only served the top level would return the page and
    then 404 everything it asks for, which looks like a blank screen and no
    error anyone can act on."""
    assets = sorted((UI_DIR / "assets").glob("*.js"))
    assert assets, "no built interface — run npm run build in gateway/webui"
    for asset in assets:
        assert client().get(f"/ui/assets/{asset.name}").status_code == 200, asset.name


@pytest.mark.parametrize(
    "path",
    [
        "../webui.py",
        "../../app/webui.py",
        "assets/../../webui.py",
        "....//webui.py",
        "/etc/passwd",
    ],
)
def test_nothing_outside_the_interface_directory_is_served(path):
    assert client().get(f"/ui/{path}").status_code == 404


def test_a_file_with_the_wrong_kind_is_not_served():
    """Only the kinds a browser needs. Anything else in that directory — a
    stray note, a source map left behind, a build manifest — is not a
    download this route offers."""
    assert client().get("/ui/notes.txt").status_code == 404
    assert client().get("/ui/assets/manifest.json").status_code == 404


def test_a_missing_file_is_a_404_rather_than_an_error():
    assert client().get("/ui/assets/nosuch.js").status_code == 404


def test_the_interface_is_served_without_a_token():
    """It is the sign-in screen; it cannot require having signed in."""
    asset = sorted((UI_DIR / "assets").glob("*.js"))[0]
    assert client().get(f"/ui/assets/{asset.name}").status_code == 200
