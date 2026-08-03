# Roadmap

Honest status. Anything not marked *done* is not built yet.

## Done

- **Engine bridge.** One engine process per tenant over stdio, with idle
  reaping, timeout recovery and per-tenant `CBM_CACHE_DIR` / `CBM_ALLOWED_ROOT`.
- **MCP over HTTP.** `initialize`, `tools/list`, `tools/call`, single and batch.
- **Identity.** OIDC/JWT verification against JWKS, LDAP groups arriving as
  claims, and a development mode with a static token.
- **Authorization.** Role capabilities, squad tenancy, project allowlists and
  the engine's own tool profile — three independent layers.
- **Audit.** One structured JSON record per call, including denials.
- **Discovery.** GitHub organisations, GitLab groups (nested subgroups) and
  Bitbucket workspaces or projects, with include/exclude globs — and a
  `connector check` that runs real discovery before a connector is trusted.
- **Indexing triggers.** Verified webhooks for all three providers, a periodic
  rescan, and a CI trigger endpoint.
- **Reasoning layer.** LiteLLM-backed `explain_change_impact` and
  `ask_codebase`, with a per-squad answer cache keyed on the index epoch
  ([ADR-0009](adr/0009-answer-cache.md)).
- **Configuration in the database.** Squads, roles, connectors and encrypted
  secrets in PostgreSQL, changed without a restart, through an admin API and a
  matching CLI ([ADR-0006](adr/0006-configuration-in-the-database.md)).
- **Web interface.** The engine's own React and Three.js interface, adopted
  ([ADR-0011](adr/0011-adopt-the-upstream-interface.md)) and pointed at `/mcp`:
  the 3D graph through an authorized layout proxy, search, `ask_codebase`, and
  the administrative console. The first administrator is created in the browser
  on first open ([ADR-0012](adr/0012-first-run-in-the-browser.md)).
- **Observability.** Prometheus metrics on both services: queue depth, tool and
  index latency, engine process count and restarts, model backend outcomes.
- **Packaging.** Multi-stage images with a pinned engine build, on Docker or
  Podman; a Helm chart covering autoscaling, PDBs, ServiceMonitors,
  NetworkPolicies and ingress; and a Compose stack for evaluation.
- **Upgrades.** `make upgrade` checks GitHub for a newer release and applies it,
  and the interface shows a banner when one is out.
- **Docs and site.** The reference documentation, rendered onto a live project
  site by Docusaurus.
- **Scripts.** Setup, test, dev, debug, smoke and end-to-end runs — see
  [development.md](development.md).

## Next

**1. The organisation-wide shared layer.** `cross-repo-intelligence` runs and
the `structural_only` tenant flag exists, but the nightly job that builds
`org/public` is not wired up. Small job, unlocks cross-squad topology answers.

**2. Graph history.** Retained snapshots plus a diff service, so before/after
comparison over time works. Designed in [ADR-0004](adr/0004-graph-history.md),
not implemented.

**3. Durable job queue.** The indexer coalesces and serialises in-process,
correct for a single replica; horizontal scaling needs Redis or NATS and
per-project locking that survives a restart. This is what keeps
`indexer.replicaCount` pinned to 1 today.

**4. Synced gateway replicas.** Topology 3 in [scaling.md](scaling.md): the
indexer publishes `graph.db.zst` artifacts and each gateway replica keeps a
local copy, removing shared storage from horizontal scaling entirely. Designed
in [ADR-0005](adr/0005-storage-topology.md), not implemented.

**5. On-demand branch indexing.** Querying a feature branch the central index
has never seen. Needs ephemeral workers, a TTL cache and a per-user quota,
since it is the one path where a single request can cost minutes of CPU.

**6. Chatbot adapter.** The MCP endpoint is already usable by anything that
speaks MCP. A thin adapter for platforms that do not would widen reach.

## Not planned

- **Forking the engine.** See [ADR-0001](adr/0001-wrap-dont-fork.md).
- **Replacing the embedding model.** It is compiled into the engine binary and
  cannot be redirected. If the bundled model proves insufficient, the answer is
  a second vector layer beside it, not a fork.
- **Replacing local use.** The `graph.db.zst` artifact is meant to be shared
  with developer machines so a local engine bootstraps from it. Central indexing and
  local use are complementary.
