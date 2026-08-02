from __future__ import annotations

import pytest

from app.auth import Principal
from app.config import Settings
from app.llm import LlmClient
from app.mcp import AccessDenied, McpRouter, Session, TenantSelectionError, build_session
from app.roles import Role
from app.tenants import TenantRegistry

CONFIG = {
    "roles": {
        "admin": ["platform-admins"],
        "developer": ["squad-payments"],
        "devops": ["chapter-devops"],
        "viewer": ["contractors"],
    },
    "tenants": {
        "payments": {
            "ldap_groups": ["squad-payments", "platform-admins", "chapter-devops", "contractors"],
            "tool_profile": "all",
            "projects": ["payments-*"],
        },
        "platform": {
            "ldap_groups": ["squad-platform"],
            "tool_profile": "analysis",
            "projects": ["*"],
        },
    },
}


def settings(tmp_path=None) -> Settings:
    return Settings(
        oidc_issuer="",
        oidc_audience="repo-mcp",
        oidc_groups_claim="groups",
        dev_insecure_auth=True,
        dev_static_token="t",
        dev_static_groups=(),
        cbm_binary="codebase-memory-mcp",
        cbm_cache_root=__import__("pathlib").Path("/var/lib/repo-mcp/cache"),
        cbm_repo_root=__import__("pathlib").Path("/var/lib/repo-mcp/repos"),
        cbm_idle_timeout_s=900.0,
        cbm_call_timeout_s=120.0,
        litellm_base_url="",
        litellm_api_key="",
        litellm_model="test",
        litellm_timeout_s=30.0,
        smart_tools_enabled=False,
    )


@pytest.fixture
def registry() -> TenantRegistry:
    return TenantRegistry.from_dict(CONFIG)


@pytest.fixture
def router(registry) -> McpRouter:
    return McpRouter(settings(), registry, pool=None, llm=LlmClient(settings()))


def session_for(registry, groups: set[str], tenant: str = "payments") -> Session:
    principal = Principal(subject="s", username="u", groups=frozenset(groups))
    return build_session(registry, principal, tenant)


def test_developer_cannot_trigger_indexing(router, registry):
    session = session_for(registry, {"squad-payments"})
    assert session.role is Role.DEVELOPER
    with pytest.raises(AccessDenied):
        router._authorize(session, "index_repository", {"repo_path": "/x"})


def test_admin_can_delete_projects(router, registry):
    session = session_for(registry, {"platform-admins"})
    router._authorize(session, "delete_project", {"project": "payments-api"})


def test_devops_cannot_read_source(router, registry):
    session = session_for(registry, {"chapter-devops"})
    assert session.role is Role.DEVOPS
    with pytest.raises(AccessDenied):
        router._authorize(session, "get_code_snippet", {"project": "payments-api"})
    # but may still inspect topology
    router._authorize(session, "trace_path", {"project": "payments-api"})


def test_viewer_is_read_only(router, registry):
    session = session_for(registry, {"contractors"})
    router._authorize(session, "search_graph", {"project": "payments-api"})
    for tool in ("query_graph", "get_code_snippet", "detect_changes"):
        with pytest.raises(AccessDenied):
            router._authorize(session, tool, {"project": "payments-api"})


def test_project_outside_allowlist_is_denied(router, registry):
    session = session_for(registry, {"squad-payments"})
    with pytest.raises(AccessDenied, match="no access to project"):
        router._authorize(session, "search_graph", {"project": "hr-portal"})


def test_index_repository_path_must_be_under_tenant_root(router, registry):
    session = session_for(registry, {"platform-admins"})
    with pytest.raises(AccessDenied, match="must live under"):
        router._authorize(session, "index_repository", {"repo_path": "/etc"})
    router._authorize(
        session, "index_repository", {"repo_path": "/var/lib/repo-mcp/repos/payments/api"}
    )


def test_tenant_profile_still_caps_an_admin(registry):
    principal = Principal(
        subject="s", username="u", groups=frozenset({"squad-platform", "platform-admins"})
    )
    session = build_session(registry, principal, "platform")
    assert session.role is Role.ADMIN
    # The platform tenant runs the analysis profile, which has no write tools.
    assert "delete_project" not in session.effective_tools
    assert "search_graph" in session.effective_tools


def test_multiple_squads_require_explicit_selection(registry):
    principal = Principal(
        subject="s", username="u", groups=frozenset({"squad-payments", "squad-platform"})
    )
    with pytest.raises(TenantSelectionError, match="X-Tenant"):
        build_session(registry, principal, None)


def test_unmapped_user_gets_no_tenant(registry):
    principal = Principal(subject="s", username="u", groups=frozenset({"nobody"}))
    with pytest.raises(TenantSelectionError, match="map to a squad"):
        build_session(registry, principal, None)


def test_requesting_an_unreachable_squad_is_denied(registry):
    principal = Principal(subject="s", username="u", groups=frozenset({"squad-payments"}))
    with pytest.raises(TenantSelectionError, match="no access to squad"):
        build_session(registry, principal, "platform")


def test_smart_tools_denied_when_llm_is_disabled(router, registry):
    session = session_for(registry, {"squad-payments"})
    with pytest.raises(AccessDenied, match="smart tools are disabled"):
        router._authorize(session, "ask_codebase", {"project": "payments-api"})
