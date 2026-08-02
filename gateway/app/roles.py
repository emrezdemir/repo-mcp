"""Role model.

Two axes are kept deliberately separate:

* **Role** decides *what you may do* (a capability set).
* **Squad / chapter membership** decides *which data you may do it to*.

Collapsing them produces a combinatorial mess — you would need a separate
definition for "the DevOps engineer embedded in the payments squad" and for
every other pairing. Keeping them orthogonal means N roles + M squads instead
of N×M definitions.

See docs/adr/0003-rbac-model.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    #: Read the graph: search, traversal, architecture summaries.
    READ_GRAPH = "read_graph"
    #: Read source text (get_code_snippet, search_code).
    READ_SOURCE = "read_source"
    #: Run raw Cypher-like queries.
    QUERY_RAW = "query_raw"
    #: Change-impact / blast-radius analysis.
    ANALYZE_CHANGES = "analyze_changes"
    #: Trigger (re)indexing.
    TRIGGER_INDEX = "trigger_index"
    #: Create and update Architecture Decision Records.
    MANAGE_ADR = "manage_adr"
    #: Upload runtime traces to validate inferred HTTP edges.
    INGEST_TRACES = "ingest_traces"
    #: Delete projects, edit tenant config, manage connectors.
    ADMINISTER = "administer"
    #: Use the LLM-backed composite tools.
    USE_SMART_TOOLS = "use_smart_tools"


class Role(StrEnum):
    ADMIN = "admin"
    LEAD = "lead"
    DEVELOPER = "developer"
    QA = "qa"
    DEVOPS = "devops"
    VIEWER = "viewer"


_DEVELOPER = frozenset(
    {
        Capability.READ_GRAPH,
        Capability.READ_SOURCE,
        Capability.QUERY_RAW,
        Capability.ANALYZE_CHANGES,
        Capability.USE_SMART_TOOLS,
    }
)

ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),
    Role.LEAD: _DEVELOPER | {Capability.TRIGGER_INDEX, Capability.MANAGE_ADR},
    Role.DEVELOPER: _DEVELOPER,
    # QA chapter: needs code and impact analysis to reason about test
    # coverage, but indexing and ADR ownership are not their job.
    Role.QA: _DEVELOPER,
    # DevOps chapter: cares about topology, routes and deployment impact
    # rather than function bodies, and owns runtime trace ingestion.
    Role.DEVOPS: frozenset(
        {
            Capability.READ_GRAPH,
            Capability.QUERY_RAW,
            Capability.ANALYZE_CHANGES,
            Capability.TRIGGER_INDEX,
            Capability.INGEST_TRACES,
            Capability.USE_SMART_TOOLS,
        }
    ),
    Role.VIEWER: frozenset({Capability.READ_GRAPH}),
}

#: Capability required to call each tool.
TOOL_CAPABILITY: dict[str, Capability] = {
    "search_graph": Capability.READ_GRAPH,
    "trace_path": Capability.READ_GRAPH,
    "get_graph_schema": Capability.READ_GRAPH,
    "get_architecture": Capability.READ_GRAPH,
    "list_projects": Capability.READ_GRAPH,
    "index_status": Capability.READ_GRAPH,
    "check_index_coverage": Capability.READ_GRAPH,
    "get_code_snippet": Capability.READ_SOURCE,
    "search_code": Capability.READ_SOURCE,
    "query_graph": Capability.QUERY_RAW,
    "detect_changes": Capability.ANALYZE_CHANGES,
    "index_repository": Capability.TRIGGER_INDEX,
    "manage_adr": Capability.MANAGE_ADR,
    "ingest_traces": Capability.INGEST_TRACES,
    "delete_project": Capability.ADMINISTER,
}

#: Most privileged first. Used when a user's LDAP groups map to several roles.
ROLE_PRECEDENCE: tuple[Role, ...] = (
    Role.ADMIN,
    Role.LEAD,
    Role.DEVOPS,
    Role.QA,
    Role.DEVELOPER,
    Role.VIEWER,
)


@dataclass(frozen=True)
class RoleAssignment:
    role: Role
    ldap_groups: frozenset[str]

    @property
    def capabilities(self) -> frozenset[Capability]:
        return ROLE_CAPABILITIES[self.role]


def resolve_role(
    assignments: tuple[RoleAssignment, ...], groups: frozenset[str]
) -> Role:
    """Resolve a user's effective role; the most privileged match wins."""
    matched = {a.role for a in assignments if a.ldap_groups & groups}
    for role in ROLE_PRECEDENCE:
        if role in matched:
            return role
    return Role.VIEWER


def capabilities_for(role: Role) -> frozenset[Capability]:
    return ROLE_CAPABILITIES[role]
