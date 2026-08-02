# ADR-0002: Two-layer tenancy for squad isolation and cross-repository visibility

- **Status:** Accepted
- **Context:** Builds on [ADR-0001](0001-wrap-dont-fork.md)

## Context

Squads should not read each other's source. At the same time, "who calls my
endpoint?" has to be answerable across the whole organisation.

Two verified engine behaviours put these in direct tension
([cbm-constraints.md §7](../cbm-constraints.md)):

- The isolation unit is the cache directory. Stores open as
  `<CBM_CACHE_DIR>/<project>.db` and `list_projects` returns everything in
  that directory.
- `CROSS_*` edges are only created between projects in the **same** store.

One store gives cross-repository edges and no isolation. Separate stores give
isolation and no cross-repository edges.

## Decision

Run two layers.

| Layer | Store | Contents | Access |
| --- | --- | --- | --- |
| Private | `<cache>/tenant/<squad>` | that squad's repositories, full graph | the squad, `analysis` profile |
| Shared | `<cache>/org/public` | all services, structural nodes plus `CROSS_*` edges | everyone, `scout` profile, `structural_only: true` |

The shared layer is produced by the indexer using
`mode: "cross-repo-intelligence"`, which skips extraction entirely and only
matches routes and channels across projects to create `CROSS_HTTP_CALLS`,
`CROSS_ASYNC_CALLS` and `CROSS_CHANNEL` edges.

## Rationale

What is genuinely needed across squads is **topology**: which service calls
which endpoint, which queue someone listens on. Function bodies are not.
Keeping the shared layer structural answers the question while making source
disclosure impossible by construction rather than by policy.

Two independent mechanisms guarantee this. The `scout` profile already
excludes `query_graph` and `search_code`; `structural_only` additionally
withholds `get_code_snippet` at the gateway. Neither relies on the other.

## Consequences

**Positive**

- Isolation is enforced by the filesystem, so a single ACL bug does not
  disclose source.
- The shared layer is one store, so cross-repository edges work normally.
- Moving or backing up a tenant is a directory copy.

**Negative, accepted**

- Repositories are indexed twice — fully in the private layer, structurally in
  the shared one. `cross-repo-intelligence` mode is cheap, but this is still
  real storage and nightly runtime.
- A squad with a legitimate need for another squad's code requires an explicit
  allowlist entry. That is deliberate, not an oversight.
- The shared layer lags (nightly). Acceptable for topology questions.

## Alternatives considered

**One store with gateway filtering.** Rejected: all source would sit in one
directory and a single authorization mistake would expose everything. No
defence in depth.

**One store per repository.** Rejected: no cross-repository edges at all, and
process and file counts grow linearly with the repository count.
