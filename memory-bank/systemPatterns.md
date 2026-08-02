# System patterns

Architecture as it stands, and the invariants that must not break. Full
explanation in [docs/architecture.md](../docs/architecture.md); the reasoning
behind each decision is in [docs/adr/](../docs/adr/).

## Shape

```
 Agents · Chatbots · CI ──MCP over HTTP + OIDC──▶ Gateway ──stdio──▶ engine
                                                    │                (per tenant)
                                                    └──HTTPS──▶ LiteLLM

 GitHub · GitLab · Bitbucket ──webhook/schedule/CI──▶ Indexer ──▶ graph store
```

Two services, one embedded engine, one shared graph store per tenant.

## Invariants

Each of these is load-bearing. If a change appears to require breaking one,
that is an architecture change: write an ADR before writing code.

### 1. Three independent authorization layers

| Layer | Enforced by | Catches |
| --- | --- | --- |
| Role capabilities ∩ tenant tool profile ∩ project allowlist | `gateway/app/mcp.py` | a caller reaching a tool or project they should not |
| `--tool-profile` allowlist | the engine process | a gateway bug widening the surface |
| `CBM_CACHE_DIR` / `CBM_ALLOWED_ROOT` per tenant | the filesystem | a process reaching another squad's data at all |

None may depend on another being correct. The effective tool set is an
**intersection**, so neither role nor tenant can widen the other.

### 2. Roles and squads are orthogonal

Role decides *what you may do* (capabilities), squad membership decides *to
which data*. N + M definitions instead of N × M
([ADR-0003](../docs/adr/0003-rbac-model.md)).

### 3. The cache directory is the isolation unit

The engine stores `<CBM_CACHE_DIR>/<project>.db`, flat, and `list_projects`
returns everything in that directory. Squad isolation therefore *requires* a
separate cache directory — it cannot be achieved by filtering output
([ADR-0002](../docs/adr/0002-tenancy-model.md)).

Corollary: the indexer must never write a project into a tenant directory that
does not allow it. The gateway warns at startup when it finds one, and
`make debug` reports it.

### 4. One writer, many readers

The indexer writes; the gateway reads. Both mount the cache read-write anyway
— SQLite in WAL mode creates `-wal` and `-shm` files in order to *read*. The
write restriction is enforced by the tool profile, not the mount
([ADR-0005](../docs/adr/0005-storage-topology.md)).

Never put the cache on NFS. WAL locking is unreliable there and corrupts
stores silently.

### 5. The engine is a binary with a contract

Never forked, never vendored. Consequences that constantly matter:

- **stdio only**, line-delimited JSON-RPC. The bridge is ours
  (`gateway/app/cbm.py`).
- **Exact-build admission barrier**: every process sharing a cache root must
  be the same build. Hence one pinned image and `Recreate`, never
  `RollingUpdate`.
- **No LLM, no configurable embeddings.** The reasoning layer sits above, not
  underneath.
- **No history.** Only the current graph exists
  ([ADR-0004](../docs/adr/0004-graph-history.md)).

### 6. Indexing is serialised per project, and coalesced

The engine holds an OS-level mutation lock per project, so two workers on one
project only block each other. The queue serialises per project and drops
bursts that converge on the same head.

This is why `indexer.replicaCount` is pinned to 1: the queue and its locks are
in-process.

### 7. Nothing environment-specific is tracked

`.env`, `tenants.yaml` and `scan.yaml` are ignored; the `.example` files are
the tracked reference and are byte-identical on every branch. That is what
makes `main` and `dev` never conflict over configuration.

### 8. Fail closed

Unknown role, unknown tool, unknown profile, malformed config, missing token —
all deny or refuse to start. The engine's own profile parser does the same,
which is why we mirror its allowlists in `gateway/app/tenants.py` rather than
trusting the flag alone.

## Recurring patterns in the code

**Config objects are frozen dataclasses built once at startup.** Validation
happens at load, so a bad `tenants.yaml` fails at boot rather than on the
first request.

**Subprocess wrappers own their failure modes.** `gateway/app/cbm.py` tears
the process down on timeout rather than leaving the stream ambiguous, and
translates a missing binary into a named error instead of an HTTP 500.

**Metrics have bounded label sets.** Unknown method and tool names collapse to
`other` / `unknown` so a client probing random names cannot inflate
cardinality.

**Errors name the value.** `no access to project 'hr-portal' (allowed:
acme-payments-*, acme-ledger)` — the caller can act on that.
