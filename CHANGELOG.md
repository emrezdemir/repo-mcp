# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Gateway** — MCP over HTTP in front of the indexing engine: one engine
  process per tenant over stdio, with idle reaping and timeout recovery.
- **Identity** — OIDC/JWT verification against JWKS, with LDAP groups arriving
  as token claims; a development mode with a static token.
- **Authorization** — three independent layers: role capabilities and project
  allowlists in the gateway, the engine's fail-closed tool profile, and
  per-tenant filesystem roots.
- **Roles** — `admin`, `lead`, `developer`, `qa`, `devops`, `viewer`, with
  capabilities and squad scope kept orthogonal so chapter members need no
  special-casing.
- **Audit** — one structured JSON record per call, including denials.
- **Reasoning** — LiteLLM-backed `explain_change_impact` and `ask_codebase`;
  hosted, vLLM and Ollama backends are proxy configuration.
- **Discovery** — connectors for GitHub organisations, GitLab groups
  (including nested subgroups) and Bitbucket workspaces or projects, with
  include/exclude globs.
- **Indexing** — verified webhooks for all three providers, a periodic rescan,
  and a CI trigger endpoint; the queue serialises per project and coalesces
  bursts.
- **Observability** — Prometheus metrics on both services: MCP request and
  tool-call counters, tool and index latency histograms, live engine process
  count and restarts, indexing queue depth, discovery and webhook outcomes.
- **Packaging** — multi-stage images with a pinned, optionally checksummed
  engine build, running non-root under `tini`; a Compose stack with health
  checks and resource limits; a Helm chart with autoscaling, pod disruption
  budgets, ServiceMonitors, network policies and ingress.
- **Scripts** — `setup`, `test`, `dev`, `debug`, `stack`, `smoke` and `e2e`,
  plus a `Makefile` wrapping them.
- **Documentation** — architecture, source-verified engine constraints, roles
  and permissions, deployment, scaling, development, roadmap, and five
  decision records.

### Notes

- The Helm chart refuses to render a gateway HPA unless the cache volume is
  `ReadWriteMany`. A replica without access to the graph stores answers
  queries from an empty graph, which reads as a code problem rather than a
  deployment one.
- Both workloads use the `Recreate` strategy: the engine's exact-build
  admission barrier fails when old and new pods share a cache root.
- A missing or unstartable engine binary is reported as a JSON-RPC error
  naming the cause, rather than surfacing as an opaque HTTP 500.

[Unreleased]: https://github.com/emrezdemir/repo-mcp/commits/main
