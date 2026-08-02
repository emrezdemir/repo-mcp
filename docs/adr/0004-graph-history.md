# ADR-0004: Graph history comes from retained artifacts, not the engine

- **Status:** Proposed
- **Context:** "Scan periodically and keep the before and after" is a stated
  requirement; the engine does not provide it.

## Context

The engine stores exactly one graph per project: the current one. `detect_changes`
compares a working tree against a base branch using git — it does not read
stored snapshots. Reindexing a project overwrites the previous graph.

So none of these work today:

- "What did this service's dependency graph look like last quarter?"
- "Which cross-service edges appeared this month?"
- "Show how the blast radius of this module has grown over the last year."

## Decision

Build history above the engine, from artifacts the indexer already produces.

Every indexing run with `persistence: true` writes
`.codebase-memory/graph.db.zst`. The indexer uploads it to object storage,
keyed by `tenant/project/<commit-sha>`, with the commit timestamp recorded
alongside.

Retention is tiered rather than "keep everything":

| Tier | Kept |
| --- | --- |
| Recent | every indexed commit for 7 days |
| Rolling | one per day for 90 days |
| Long term | one per month, indefinitely |

A comparison request opens two snapshots read-only and diffs at node and edge
level — symbols added, removed or rewired — without going through the live
store.

## Rationale

The snapshots are a by-product we already generate for developer bootstrap, so
the marginal cost is storage rather than compute.

Diffing outside the live store keeps historical queries away from the path
that agents use interactively, and means a large historical comparison cannot
slow down day-to-day work.

Tiered retention is what makes this affordable. Keeping every commit's graph
for every repository in a large organisation is not viable; keeping every
commit for a week and monthly points forever answers the questions people
actually ask.

## Consequences

**Positive**

- Genuine before/after comparison over arbitrary time ranges.
- Snapshots double as disaster recovery for the live store.
- Comparison load is isolated from interactive queries.

**Negative, accepted**

- Object storage grows with repository count times retention. Needs measuring
  on real data before committing to the tiers above.
- The graph diff is ours to write and to keep correct across engine schema
  changes.
- Snapshots contain the full graph, including source-derived data, so they
  inherit the same access controls as the live store. Encryption at rest and
  per-tenant prefixes are required, not optional.

## Alternatives considered

**Reindex historical commits on demand.** Rejected as the primary mechanism:
correct, but indexing a year-old commit takes as long as indexing the head, so
interactive comparison would be unusable. Worth keeping as a fallback for
commits that predate the retention window.

**Store the history inside the engine.** Rejected — that is a fork
([ADR-0001](0001-wrap-dont-fork.md)), and versioned graph storage is a much
larger change than the transport and auth gaps we are already filling.
