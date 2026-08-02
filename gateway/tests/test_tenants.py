from __future__ import annotations

import pytest

from app.roles import Role
from app.tenants import ConfigError, TenantRegistry

BASE = {
    "roles": {
        "admin": ["platform-admins"],
        "lead": ["squad-payments-leads"],
        "developer": ["squad-payments", "squad-platform"],
        "qa": ["chapter-test"],
        "devops": ["chapter-devops"],
    },
    "tenants": {
        "payments": {
            "ldap_groups": ["squad-payments", "squad-payments-leads"],
            "tool_profile": "analysis",
            "projects": ["payments-*", "ledger"],
        },
        "org-public": {
            "ldap_groups": ["all-engineers"],
            "tool_profile": "scout",
            "projects": ["*"],
            "structural_only": True,
        },
    },
}


def registry(**overrides) -> TenantRegistry:
    return TenantRegistry.from_dict({**BASE, **overrides})


def test_project_allowlist_matches_glob_patterns():
    payments = registry().by_name("payments")
    assert payments.allows_project("payments-api")
    assert payments.allows_project("ledger")
    assert not payments.allows_project("hr-portal")
    assert not payments.allows_project("")


def test_structural_only_withholds_source_reading_tools():
    public = registry().by_name("org-public")
    assert "get_code_snippet" not in public.allowed_tools
    assert "search_code" not in public.allowed_tools
    assert "search_graph" in public.allowed_tools


def test_analysis_profile_excludes_write_tools():
    payments = registry().by_name("payments")
    for tool in ("index_repository", "delete_project", "manage_adr", "ingest_traces"):
        assert not payments.allows_tool(tool)


def test_cbm_profile_flag_matches_configured_profile():
    reg = registry()
    assert reg.by_name("payments").cbm_profile_flag() == ["--tool-profile=analysis"]
    assert reg.by_name("org-public").cbm_profile_flag() == ["--tool-profile=scout"]


def test_full_profile_passes_no_flag():
    reg = TenantRegistry.from_dict(
        {"tenants": {"t": {"ldap_groups": ["g"], "tool_profile": "all", "projects": ["*"]}}}
    )
    assert reg.by_name("t").cbm_profile_flag() == []


def test_group_mapped_to_two_tenants_is_rejected():
    config = {
        "tenants": {
            "a": {"ldap_groups": ["shared"], "projects": ["*"]},
            "b": {"ldap_groups": ["shared"], "projects": ["*"]},
        }
    }
    with pytest.raises(ConfigError, match="mapped to both"):
        TenantRegistry.from_dict(config)


def test_unknown_tool_profile_is_rejected():
    config = {
        "tenants": {"a": {"ldap_groups": ["g"], "projects": ["*"], "tool_profile": "root"}}
    }
    with pytest.raises(ConfigError, match="unknown tool_profile"):
        TenantRegistry.from_dict(config)


def test_a_tenant_entry_that_is_not_a_mapping_is_rejected():
    with pytest.raises(ConfigError, match="must be a mapping"):
        TenantRegistry.from_dict({"tenants": {"a": ["not", "a", "mapping"]}})


def test_role_resolution_prefers_the_most_privileged_match():
    reg = registry()
    assert reg.role_for(frozenset({"squad-payments"})) is Role.DEVELOPER
    assert reg.role_for(frozenset({"squad-payments", "platform-admins"})) is Role.ADMIN
    assert reg.role_for(frozenset({"squad-payments", "squad-payments-leads"})) is Role.LEAD
    assert reg.role_for(frozenset({"chapter-devops", "squad-payments"})) is Role.DEVOPS


def test_unknown_groups_fall_back_to_viewer():
    assert registry().role_for(frozenset({"random-group"})) is Role.VIEWER


def test_for_groups_returns_only_reachable_tenants():
    reachable = registry().for_groups(frozenset({"squad-payments"}))
    assert [t.name for t in reachable] == ["payments"]


def test_unknown_role_name_is_rejected():
    with pytest.raises(ConfigError, match="unknown role"):
        TenantRegistry.from_dict({**BASE, "roles": {"superuser": ["g"]}})


def test_an_empty_registry_is_valid_not_an_error():
    """A freshly bootstrapped database has no squads yet.

    Treating that as a configuration error crashed the gateway on first boot,
    which is the most common state a new deployment is in.
    """
    empty = TenantRegistry.from_dict({})
    assert empty.tenants == ()
    assert empty.for_groups(frozenset({"anyone"})) == ()
    assert empty.role_for(frozenset({"anyone"})) is Role.VIEWER


def test_a_malformed_tenants_section_is_still_rejected():
    with pytest.raises(ConfigError, match="must be a mapping"):
        TenantRegistry.from_dict({"tenants": ["not", "a", "mapping"]})
