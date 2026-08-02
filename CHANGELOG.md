# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Gateway** — MCP over HTTP in front of codebase-memory-mcp: one engine
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
- **Documentation** — architecture, source-verified engine constraints, roles
  and permissions, deployment, roadmap, and four decision records.

[Unreleased]: https://github.com/emrezdemir/repo-mcp/commits/main
