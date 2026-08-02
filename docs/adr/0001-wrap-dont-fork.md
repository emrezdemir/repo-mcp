# ADR-0001: Wrap the engine rather than fork it

- **Status:** Accepted
- **Context:** Building a central, multi-tenant, LDAP-protected code
  intelligence platform on top of an existing indexing engine

## Context

The engine already produces the knowledge graph we want, but has none of what a
central deployment needs: no network transport, no authentication, no
multi-tenancy (see [engine.md](../engine.md)).

Two options:

1. **Fork** — add HTTP transport, auth and tenancy to the engine itself.
2. **Wrap** — leave the engine untouched and solve the gaps in a service above it.

## Decision

Wrap. We never modify the engine binary; we use only its CLI and stdio
interfaces, its environment variables and its `--tool-profile` flag.

## Rationale

**Forking costs far more than it returns.** The engine vendors 158 tree-sitter
grammars, a hand-written hybrid LSP layer for eleven languages, a compiled-in
embedding model, and a release pipeline with SLSA provenance and Sigstore
signatures. Upstream maintains all of it today. In a fork, we would — including
backporting security fixes.

**Everything we want to add belongs outside anyway.** A transport bridge, JWT
verification, an ACL and an audit trail are not problems that deserve to be
written in C inside a parser. They belong in a service we can write in a
language our team already operates, and change without recompiling an engine.

**Upstream supports this usage.** `CBM_ALLOWED_ROOT` is documented for
untrusted-caller and agentic-wrapper deployments, and
`--tool-profile=analysis|scout` is a fail-closed tool allowlist. Wrapping is a
supported mode, not something we are forcing.

**The bridge is cheap.** The protocol is line-delimited JSON-RPC; the client
is a few hundred lines. Running one process per tenant is what we want for
isolation regardless.

## Consequences

**Positive**

- Upstream releases are adopted by changing a pinned version.
- The security surface is ours: changing authorization does not mean
  recompiling C.
- The gateway is testable against a fake engine, independently of the real engine.

**Negative, accepted**

- One process per tenant: memory and process supervision are our problem.
- We cannot change engine behaviour. For example `list_projects` returns
  everything in a cache directory, so the cache directory has to *be* the
  isolation boundary rather than something we filter after the fact.
- Upstream tool schemas can change under us. This is mitigated by pinning the
  version and by contract tests.

## Alternatives considered

**Fork the engine and add transport, auth and tenancy inside it.** Rejected.
It would put 158 vendored grammars, a hand-written LSP layer and a signed
release pipeline under our maintenance, including backporting upstream
security fixes. The features we actually need are all outside the parser.

**Reimplement the graph engine ourselves.** Rejected as an order of magnitude
more work than the entire rest of this project, for a component that already
exists, is MIT licensed and is faster than anything we would write.

**Run the engine per developer and only centralise coordination.** Rejected:
it keeps the duplicated indexing that is the problem statement, and it makes
cross-repository edges impossible, since those only exist within one store.

**Contribute the missing features upstream instead.** Considered and partly
rejected on timing rather than merit — multi-tenancy and LDAP identity are
not obviously wanted in a single-user local tool, and we cannot block on that
discussion. Worth revisiting for anything that is plainly a general
improvement.

## Revisit when

If upstream adds an HTTP or streamable transport, the bridge layer becomes
unnecessary and the gateway reduces to identity, authorization and the
reasoning layer. That simplifies this decision rather than reversing it.
