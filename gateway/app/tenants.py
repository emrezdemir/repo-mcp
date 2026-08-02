"""Squad-to-tenant mapping and project allowlists.

See docs/adr/0002-tenancy-model.md for the isolation model.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .roles import Role, RoleAssignment, resolve_role

# Tools exposed by each restricted engine profile, mirrored from the engine's
# allowlist in src/mcp/mcp.c. The gateway enforces the same sets independently
# so that a missing `--tool-profile` flag cannot silently widen the surface.
ANALYSIS_TOOLS = frozenset(
    {
        "search_graph",
        "query_graph",
        "trace_path",
        "get_code_snippet",
        "get_graph_schema",
        "get_architecture",
        "search_code",
        "list_projects",
        "index_status",
        "check_index_coverage",
        "detect_changes",
    }
)

SCOUT_TOOLS = frozenset(
    {
        "search_graph",
        "trace_path",
        "get_code_snippet",
        "get_architecture",
        "list_projects",
        "index_status",
        "check_index_coverage",
    }
)

WRITE_TOOLS = frozenset(
    {"index_repository", "delete_project", "manage_adr", "ingest_traces"}
)

ALL_TOOLS = ANALYSIS_TOOLS | SCOUT_TOOLS | WRITE_TOOLS

PROFILES: dict[str, frozenset[str]] = {
    "all": ALL_TOOLS,
    "analysis": ANALYSIS_TOOLS,
    "scout": SCOUT_TOOLS,
}


class ConfigError(ValueError):
    """tenants.yaml is malformed."""


@dataclass(frozen=True)
class Tenant:
    name: str
    ldap_groups: frozenset[str]
    tool_profile: str
    projects: tuple[str, ...]
    #: Shared org-wide layer: tools that return source text are withheld.
    structural_only: bool = False
    denied_tools: frozenset[str] = field(default_factory=frozenset)
    #: Name of the environment variable holding this squad's LiteLLM virtual
    #: key. The key itself is never written to configuration files.
    litellm_key_env: str | None = None

    @property
    def allowed_tools(self) -> frozenset[str]:
        tools = PROFILES[self.tool_profile]
        if self.structural_only:
            tools = tools - {"get_code_snippet", "search_code"}
        return tools - self.denied_tools

    def cbm_profile_flag(self) -> list[str]:
        """Flag passed to the engine process; the full profile passes none."""
        if self.tool_profile == "all":
            return []
        return [f"--tool-profile={self.tool_profile}"]

    def allows_project(self, project: str) -> bool:
        if not project:
            return False
        return any(fnmatch.fnmatchcase(project, pat) for pat in self.projects)

    def allows_tool(self, tool: str) -> bool:
        return tool in self.allowed_tools


@dataclass(frozen=True)
class TenantRegistry:
    tenants: tuple[Tenant, ...]
    role_assignments: tuple[RoleAssignment, ...] = ()

    @classmethod
    def load(cls, path: Path) -> TenantRegistry:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError as exc:  # pragma: no cover - operational failure
            raise ConfigError(f"cannot read tenants file {path}: {exc}") from exc
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> TenantRegistry:
        entries = raw.get("tenants")
        if entries is None:
            entries = {}
        if not isinstance(entries, dict):
            raise ConfigError("'tenants' must be a mapping of squad name to definition")

        # An empty registry is a legitimate state, not an error: a freshly
        # bootstrapped database has no squads until an administrator adds the
        # first one. The service starts, reports it, and denies every request
        # with "none of your LDAP groups map to a squad" — which is true.
        tenants: list[Tenant] = []
        seen_groups: dict[str, str] = {}
        for name, cfg in entries.items():
            if not isinstance(cfg, dict):
                raise ConfigError(f"tenant {name!r} must be a mapping")

            profile = str(cfg.get("tool_profile", "analysis"))
            if profile not in PROFILES:
                raise ConfigError(
                    f"tenant {name!r}: unknown tool_profile {profile!r} "
                    f"(expected one of {', '.join(sorted(PROFILES))})"
                )

            groups = cfg.get("ldap_groups") or []
            if not isinstance(groups, list) or not groups:
                raise ConfigError(f"tenant {name!r}: ldap_groups must not be empty")

            projects = cfg.get("projects") or []
            if not isinstance(projects, list) or not projects:
                raise ConfigError(f"tenant {name!r}: projects must not be empty")

            for group in groups:
                # Mapping one LDAP group to two tenants makes the effective
                # isolation boundary ambiguous. Fail loudly instead of picking.
                if group in seen_groups:
                    raise ConfigError(
                        f"LDAP group {group!r} is mapped to both "
                        f"{seen_groups[group]!r} and {name!r}"
                    )
                seen_groups[group] = str(name)

            tenants.append(
                Tenant(
                    name=str(name),
                    ldap_groups=frozenset(str(g) for g in groups),
                    tool_profile=profile,
                    projects=tuple(str(p) for p in projects),
                    structural_only=bool(cfg.get("structural_only", False)),
                    denied_tools=frozenset(str(t) for t in cfg.get("denied_tools", [])),
                    litellm_key_env=(
                        str(cfg["litellm_key_env"]) if cfg.get("litellm_key_env") else None
                    ),
                )
            )
        return cls(tuple(tenants), _parse_roles(raw.get("roles") or {}))

    def for_groups(self, groups: frozenset[str]) -> tuple[Tenant, ...]:
        """Tenants reachable with the given LDAP group membership."""
        return tuple(t for t in self.tenants if t.ldap_groups & groups)

    def role_for(self, groups: frozenset[str]) -> Role:
        return resolve_role(self.role_assignments, groups)

    def by_name(self, name: str) -> Tenant | None:
        return next((t for t in self.tenants if t.name == name), None)


def _parse_roles(raw: dict) -> tuple[RoleAssignment, ...]:
    assignments: list[RoleAssignment] = []
    for role_name, groups in raw.items():
        try:
            role = Role(str(role_name))
        except ValueError as exc:
            valid = ", ".join(r.value for r in Role)
            raise ConfigError(
                f"unknown role {role_name!r} (expected one of {valid})"
            ) from exc
        if not isinstance(groups, list) or not groups:
            raise ConfigError(f"role {role_name!r}: group list must not be empty")
        assignments.append(
            RoleAssignment(role=role, ldap_groups=frozenset(str(g) for g in groups))
        )
    return tuple(assignments)
