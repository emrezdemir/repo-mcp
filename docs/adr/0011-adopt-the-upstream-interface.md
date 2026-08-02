# ADR-0011: Adopt the engine's interface rather than write our own

- **Status:** Accepted
- **Context:** The web interface, and how much of the engine's project to reuse

## Context

[ADR-0001](0001-wrap-dont-fork.md) decided to wrap the engine rather than fork
it, and that decision stands for the engine. It was applied too widely: it was
read as "take nothing from the upstream project", and a web interface was
written from scratch — vanilla ES modules over Sigma, about 2,500 lines.

The upstream project already has one. It is 60 files of React 19 and Three.js
under `graph-ui/`, MIT licensed, and it renders the graph in 3D from a layout
the engine computes in C. Put side by side with the one written here, it is
better: edges coloured per relationship type, a folder tree, dead-code and
entry-point overlays, and a look that makes a 20 000-node graph legible rather
than merely drawn.

The two decisions are not the same decision. The engine is 1,229 C files, 43 MB
of vendored dependencies and a signed release pipeline; forking it means owning
all of that. `graph-ui` is 60 files that talk JSON-RPC over HTTP and move
independently of the engine.

## Decision

Adopt `graph-ui` into this repository, at a recorded upstream commit, and point
its transport at the gateway. Delete the interface written here.

The engine itself is still wrapped, not forked. ADR-0001 is unchanged.

## Rationale

**The protocol was already the same.** Upstream's client posts
`{"jsonrpc":"2.0","method":"tools/call",…}` to `/rpc`; the gateway accepts
exactly that at `/mcp`. Adoption cost a URL and two headers, not a rewrite.

**Every tool it needs, this platform already exposes.** `list_projects`,
`get_graph_schema` and `get_code_snippet`, each behind a capability. The other
things it reached for — project health, ADRs, indexing, deletion, git metadata
— are all engine tools too, so they moved from unauthenticated local endpoints
to authorized tool calls without losing function.

**Rendering a real graph is not a small piece of work.** The 3D layout is 860
lines of C reading the graph database directly, and the renderer is a
postprocessing pipeline over Three.js. Both already exist, are maintained
upstream, and are the part a person actually looks at.

**Divergence is bounded and visible.** 60 files with a recorded upstream
commit can be diffed against a newer version. A rewrite cannot.

## Consequences

**Positive**

- The interface is the one the engine's authors designed for this graph.
- Improvements upstream can be taken by diffing against the recorded commit.
- Every request still goes through `/mcp`, so there is exactly one place the
  tenancy rules are enforced.

**Negative, accepted**

- **A build step, and a second dependency ecosystem.** Node, a lockfile and a
  Vite stage in the image. The "no toolchain in this repository" property is
  gone. Nothing is fetched at runtime, so an air-gapped *installation* still
  works — but an air-gapped *build* now needs an npm mirror as well as a
  Python one.
- **The engine build got larger and more specific.** The graph needs the
  edition with the interface compiled in (`CBM_EDITION=-ui`), because the
  layout is served by that binary. Without it the graph page explains itself
  and the rest of the interface works.
- **A loopback port per tenant.** The gateway starts each tenant's engine with
  its layout server and proxies to it. That port has no authentication of its
  own, which is why it binds 127.0.0.1, is chosen by the gateway, and is never
  published — the same trust boundary the stdio pipe already has.
- **Upstream drift is now our problem.** Files we changed will conflict with
  upstream changes to the same files. `gateway/webui/README.md` records what
  was changed and why, so a merge has something to reason about.
- **Two surfaces upstream had are gone**: the filesystem browser and the
  process and log views. They are meaningful on one machine and not on a
  shared platform. Anyone used to them upstream will find them missing.

## Alternatives considered

**Keep the interface written here and copy its ideas.** Rejected. It would
mean reimplementing a 3D layout and a Three.js renderer to arrive at something
that already exists under a licence that permits using it, and the result would
be behind from the first day.

**Serve the engine's interface directly, by exposing its port.** Rejected. That
server has no authentication and no notion of a squad; publishing it would put
every tenant's graph behind a port instead of behind the ACL, and its Control
tab would hand out process control with it.

**Fork the whole upstream project and build the platform inside it.** Rejected
for the reasons in ADR-0001, which are about the engine and have not changed:
1,229 C files, 158 vendored grammars and a signed release pipeline under our
maintenance, to add things that all belong outside a parser.

**Reimplement the 3D layout in Python and serve it from the gateway.**
Rejected. It is 860 lines of C reading the graph database directly; a Python
port would be slower, would drift, and would have to be re-verified against
every engine release.

## Revisit when

If upstream adds authentication and multi-tenancy to its own server, the proxy
in `webui.py` becomes unnecessary. If `graph-ui` diverges so far that merges
stop being tractable, the choice is a hard fork of those 60 files — still a
better position than the rewrite this replaced.
