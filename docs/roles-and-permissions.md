# Roles and permissions

Authorization has two axes, kept deliberately separate
([ADR-0003](adr/0003-rbac-model.md)):

- **Role** — what you may do. A set of capabilities.
- **Squad (tenant)** — which data you may do it to.

Both come from LDAP group membership, mapped in `tenants.yaml`.

## Capabilities

| Capability | Grants |
| --- | --- |
| `read_graph` | search, traversal, architecture summaries, index status |
| `read_source` | `get_code_snippet`, `search_code` — raw source text |
| `query_raw` | free-form Cypher-like `query_graph` |
| `analyze_changes` | `detect_changes` and the blast radius |
| `trigger_index` | start a (re)index |
| `manage_adr` | create and update architecture decision records |
| `ingest_traces` | upload runtime traces to validate inferred HTTP edges |
| `administer` | delete projects, change tenant configuration |
| `use_smart_tools` | the LLM-backed composite tools |

## Roles

| | admin | lead | developer | qa | devops | viewer |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| `read_graph` | ● | ● | ● | ● | ● | ● |
| `read_source` | ● | ● | ● | ● | | |
| `query_raw` | ● | ● | ● | ● | ● | |
| `analyze_changes` | ● | ● | ● | ● | ● | |
| `use_smart_tools` | ● | ● | ● | ● | ● | |
| `trigger_index` | ● | ● | | | ● | |
| `manage_adr` | ● | ● | | | | |
| `ingest_traces` | ● | | | | ● | |
| `administer` | ● | | | | | |

`qa` and `devops` are chapter roles: they cut across squads. Someone is
`devops` **and** a member of the payments squad — the two are combined at
request time, not predefined as a pair.

`devops` intentionally has no `read_source`. The role is about topology,
routes and deployment impact; withholding function bodies limits what a
compromised CI credential can retrieve without impeding the work.

When several groups match, the most privileged role wins:
`admin > lead > devops > qa > developer > viewer`.

## How role and squad combine

The effective tool set is the **intersection** of the two axes:

```
effective_tools = tenant.allowed_tools ∩ { tools whose capability ∈ role.capabilities }
```

Neither axis can widen the other. An admin working inside a squad configured
with the `scout` profile still sees only the scout tools; a developer in a
squad configured with the full profile still cannot delete a project.

## Configuration

```yaml
roles:
  admin:     [platform-admins]
  lead:      [squad-payments-leads]
  developer: [squad-payments, squad-checkout]
  qa:        [chapter-test]
  devops:    [chapter-devops]
  viewer:    [contractors]

tenants:
  payments:
    ldap_groups: [squad-payments, squad-payments-leads, chapter-test, chapter-devops]
    tool_profile: analysis
    projects: ["acme-payments-*", "acme-ledger"]
```

Group names are written without a leading slash; Keycloak's `/group` form is
normalised on the way in.

Mapping one LDAP group to two tenants is rejected at startup — it would make
the effective isolation boundary ambiguous.

## Selecting a squad

Users in more than one squad must pick per session with the `X-Tenant` header.
The gateway refuses to choose, because guessing would silently read from the
wrong store.

```
X-Tenant: payments
```

## Auditing

Every call is logged as one JSON object with principal, role, squad, tool,
project, outcome and duration. Denials record the reason. Reading source is
just as auditable as changing anything, which is the point.
