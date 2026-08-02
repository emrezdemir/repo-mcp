# Roadmap

Honest status. Anything not marked *done* is not built yet.

## Done

- **Engine bridge.** One engine process per tenant over stdio, with idle reaping,
  timeout recovery and per-tenant `CBM_CACHE_DIR` / `CBM_ALLOWED_ROOT`.
- **MCP over HTTP.** `initialize`, `tools/list`, `tools/call`, single and
  batch requests.
- **Identity.** OIDC/JWT verification against JWKS, with LDAP groups arriving
  as claims; a development mode with a static token.
- **Authorization.** Role capabilities, squad tenancy, project allowlists, and
  the engine's own tool profile — three independent layers.
- **Audit.** One structured JSON record per call, including denials.
- **Discovery.** GitHub organisations, GitLab groups (including nested
  subgroups) and Bitbucket workspaces or projects, with include/exclude globs.
- **Indexing triggers.** Verified webhooks for all three providers, a periodic
  rescan, and a CI trigger endpoint.
- **Reasoning layer.** LiteLLM-backed `explain_change_impact` and
  `ask_codebase`; hosted, vLLM or Ollama backends are proxy configuration.
- **Observability.** Prometheus metrics on both services: queue depth, tool
  and index latency, engine process count and restarts, model backend
  outcomes.
- **Packaging.** Multi-stage images with a pinned engine build, a Helm chart
  covering autoscaling, PDBs, ServiceMonitors, NetworkPolicies and ingress,
  and a Compose stack for evaluation.
- **Scripts.** Setup, test, dev, debug, smoke and end-to-end runs — see
  [development.md](development.md).

## Next

**1. Web UI — codebase map and manual search.** The largest remaining piece,
and effectively a product of its own. The upstream 3D visualiser cannot be
reused: it binds to `127.0.0.1` by construction
([engine.md §2](engine.md)). This needs a read API over the
graph, a rendering strategy that survives large graphs (level-of-detail,
server-side layout, viewport queries), and the same authorization the MCP
surface enforces.

Sequencing note: MCP first, UI second, deliberately. The MCP surface delivers
value on day one and proves whether the graph is good enough to build a UI on.

**2. Graph history.** Retained snapshots plus a diff service, so before/after
comparison over time works. Designed in [ADR-0004](adr/0004-graph-history.md),
not implemented.

**3. On-demand branch indexing.** Querying a feature branch the central index
has never seen. Needs ephemeral workers, a TTL cache and a per-user quota,
since it is the one path where a single request can cost minutes of CPU.

**4. Durable job queue.** The indexer currently coalesces and serialises
in-process. That is correct for a single replica; horizontal scaling needs
Redis or NATS, and per-project locking that survives a restart. This is what
keeps `indexer.replicaCount` pinned to 1 today.

**4b. Synced gateway replicas.** Topology 3 in [scaling.md](scaling.md): the
indexer publishes `graph.db.zst` artifacts and each gateway replica keeps a
local copy, removing shared storage from horizontal scaling entirely. Designed
in [ADR-0005](adr/0005-storage-topology.md), not implemented.

**5. The organisation-wide shared layer.** `cross-repo-intelligence` runs and
the `structural_only` tenant flag exist, but the nightly job that builds
`org/public` is not wired up.

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
