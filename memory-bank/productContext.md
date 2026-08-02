# Product context

## Who uses this

| User | What they want | What they get |
| --- | --- | --- |
| **Developer** | "Who calls this? What breaks if I change it?" answered without leaving the editor | Their agent queries the shared graph over MCP; no local indexing |
| **Team lead** | Review help, architecture decisions written down | Blast-radius summaries on pull requests, ADR management |
| **QA / test chapter** | Which tests matter for this change | Impact analysis across the squads they are embedded in |
| **DevOps chapter** | Service topology, deployment blast radius | Routes and cross-service edges org-wide, without source access |
| **Platform admin** | Onboard a squad, keep it isolated | One connector entry, one tenant entry |
| **CI pipeline** | Fresh graph before impact analysis | A trigger endpoint and a service-account token |
| **Chatbot** | Answer questions in chat | The same MCP endpoint, same authorization |

The chapter roles are why capabilities and squad scope are kept orthogonal: a
DevOps engineer embedded in the payments squad is `devops` × `payments`, not a
tenth bespoke role ([ADR-0003](../docs/adr/0003-rbac-model.md)).

## How it is meant to feel

**For a developer: invisible.** Point the agent at one URL and forget it. No
index step, no waiting, no local cache to warm. If someone has to think about
repo-mcp while working, something is wrong.

**For a platform admin: boring.** Adding a squad is a few lines of YAML.
Adding a repository to the organisation requires nothing at all. Secrets come
from the environment; nothing per-deployment lives in git.

**For a security reviewer: checkable.** Every authorization decision is
auditable, engine behaviour claims cite source, and the three enforcement
layers can be reasoned about one at a time.

## The two questions that shaped the design

**"Can another squad read my code?"** — No, and not because of one ACL check.
Squads are separate directories on disk, engine processes run with a
fail-closed tool profile, and the gateway checks role and project allowlist
independently ([ADR-0002](../docs/adr/0002-tenancy-model.md)).

**"Then how do I find out who calls my service?"** — A shared organisation-wide
layer holds structure only: projects, routes, resources and cross-service
edges. No function bodies, by construction rather than by policy.

## Deliberate product decisions

**MCP first, web UI second.** The MCP surface delivers value on day one and
proves whether the graph is good enough to justify building a UI. The UI is
the largest remaining chunk and is explicitly not built
([docs/roadmap.md](../docs/roadmap.md)).

**The model is never asked to guess the graph.** Composite tools run the
deterministic query first and hand the result to the model. Raw tools are
proxied unchanged, so an agent that wants structure pays no tokens for it.

**Local use is not replaced.** Central indexing publishes artifacts that
local installs bootstrap from.

## What would make this fail

- **Stale graphs.** If answers lag reality, developers stop trusting it and go
  back to grep. Indexing latency is the metric that matters most.
- **A slow first onboarding.** Indexing an entire organisation at once is the
  expensive moment. The documented path is one connector in `fast` mode, then
  widen.
- **An over-eager secret scanner.** A check that cries wolf gets bypassed, and
  then it protects nothing. Patterns stay length-anchored for that reason.
- **Documentation that overstates.** If the roadmap says "done" for something
  designed, people build on sand.
