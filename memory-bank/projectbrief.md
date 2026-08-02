# Project brief

## What we are building

A self-hosted service that turns a whole organisation's repositories into a
shared, queryable knowledge graph — reachable over MCP by coding agents,
chatbots and CI pipelines, behind the company's own identity provider.

## The problem

Code intelligence tooling is built for one developer on one laptop: index
locally, query locally, throw it away. At company scale that shape fails in
four specific ways.

1. Every developer reindexes the same repositories. The work is duplicated by
   headcount.
2. No graph is ever shared, so a team cannot answer a question about code it
   does not own.
3. Cross-service questions — "who calls this endpoint?" — cannot be answered
   at all, because no single machine has all the repositories.
4. The knowledge is unreachable from anything that is not a developer's
   terminal: no chatbot, no CI job, no dashboard.

## What success looks like

- A developer's agent answers "what breaks if I change this?" from a graph
  that was built centrally, minutes after the last merge.
- A squad sees its own code in full detail and other squads' services only as
  topology.
- A pull request gets an automatic blast-radius comment without anyone
  configuring a per-repository job.
- Adding a repository to a GitHub organisation is enough for it to appear —
  no configuration change.

## Scope

**In scope**

- Repository discovery across GitHub, GitLab and Bitbucket
- Central indexing: webhook, scheduled, CI-triggered and manual
- MCP over HTTP with OIDC authentication federated from LDAP
- Squad-level tenancy, role-based capabilities, audit logging
- LLM-backed synthesis routed through the organisation's own LiteLLM proxy
- Kubernetes and Compose deployment

**Out of scope, deliberately**

- Writing our own parser or graph engine. We embed one and never fork it
  ([ADR-0001](../docs/adr/0001-wrap-dont-fork.md)).
- Replacing local use. The central service publishes artifacts that local
  installs bootstrap from; the two are complementary.
- Being a general code search product. This answers structural questions;
  text search is what grep is for.
- Hosting models. LiteLLM fronts whatever the organisation already runs.

## Non-negotiables

These constrain every design decision. They are restated as hard rules in
[AGENTS.md §5](../AGENTS.md).

1. **A squad cannot read another squad's source.** Enforced in three
   independent layers, not one.
2. **No secret or environment-specific value is ever tracked in git.**
3. **The indexing engine is never modified.** It is a binary with a contract.
4. **Documentation states what is built, separately from what is designed.**

## Who decides

The maintainer merges `dev` into `main`. Architectural changes need an ADR
before implementation, not after.
