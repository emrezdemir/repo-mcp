# ADR-0003: Roles grant capabilities, membership grants scope

- **Status:** Accepted

## Context

The platform serves several kinds of user: admins, team leads, developers, and
members of cross-cutting chapters — test and DevOps — who work across squad
boundaries.

The naive model gives each combination its own definition: "payments
developer", "payments DevOps", "checkout QA". With N roles and M squads that is
N×M definitions, and every new squad multiplies the configuration.

## Decision

Keep two orthogonal axes:

- **Role** decides *what you may do* — a set of capabilities.
- **Squad membership** decides *which data you may do it to* — a tenant.

Both are driven by LDAP group membership, mapped in `tenants.yaml`. A user's
effective tool set is the intersection: `tenant.allowed_tools ∩ tools whose
capability is in role.capabilities`.

Capabilities, rather than tool names, are the unit of authorization, so adding
an engine tool does not mean editing every role.

| Role | Capabilities |
| --- | --- |
| `admin` | everything, including `administer` |
| `lead` | developer plus `trigger_index`, `manage_adr` |
| `developer` | `read_graph`, `read_source`, `query_raw`, `analyze_changes`, `use_smart_tools` |
| `qa` | same as developer — reasoning about coverage needs the code and the impact set |
| `devops` | `read_graph`, `query_raw`, `analyze_changes`, `trigger_index`, `ingest_traces`, `use_smart_tools` — topology rather than function bodies |
| `viewer` | `read_graph` only |

When a user's groups map to several roles, the most privileged wins
(`ROLE_PRECEDENCE` in `gateway/app/roles.py`).

## Rationale

Chapters are exactly why the axes must stay separate. A DevOps engineer
embedded in the payments squad is `devops` × `payments` — no new definition
required. Adding a squad adds one tenant entry, not one entry per role.

`devops` deliberately lacks `read_source`. The role cares about routes,
dependencies and deployment impact; withholding function bodies narrows what a
compromised CI credential can retrieve without getting in anyone's way.

The intersection rule means privilege cannot be smuggled in through either
axis alone: an admin operating inside a squad configured with the `scout`
profile still only sees the scout tools.

## Consequences

**Positive**

- Configuration grows as N + M rather than N×M.
- Chapter membership needs no special-casing in code.
- New engine tools are classified once, by capability.

**Negative, accepted**

- "Most privileged role wins" can surprise: a lead who is also in
  `platform-admins` operates as an admin everywhere. Deliberate, and audited on
  every call.
- The role is global rather than per-squad. Someone who should be a lead in one
  squad and a developer in another cannot be expressed today; that needs
  per-tenant role assignment, and no one has asked for it yet.

## Alternatives considered

**One role per role × squad pairing** ("payments-developer",
"payments-devops", "checkout-qa"). Rejected: N×M definitions, and every new
squad multiplies the configuration. It is also where chapter members break
down, because they legitimately belong to several squads at once.

**Permissions attached directly to tools rather than to capabilities.**
Rejected: adding an engine tool would then mean editing every role. With
capabilities, a new tool is classified once.

**Role assignment per tenant rather than globally.** Considered and deferred.
It would express "lead in payments, developer in checkout", which is a real
situation. It also doubles the size of the configuration and nobody has asked
for it yet. Recorded as a known limitation rather than designed around.

**Deriving roles from LDAP group names by convention** (for example a
`-leads` suffix). Rejected: it makes the directory's naming scheme a load-
bearing part of the authorization model, and it fails silently when someone
renames a group.
