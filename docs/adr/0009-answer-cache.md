# ADR-0009: A per-squad answer cache, without a vector database

- **Status:** Accepted
- **Context:** `ask_codebase` and `explain_change_impact` send graph evidence to
  an LLM on every call. The same questions are asked repeatedly, and each
  repeat costs tokens and seconds.

## Context

The two composite tools ([smart_tools.py](../../gateway/app/smart_tools.py))
gather evidence from the graph and hand it to LiteLLM. A single
`ask_codebase` call sends up to 20 000 characters of evidence — roughly 5 000
tokens of input — and waits for the model.

Squads ask the same things. "How does authentication work here", "what calls
this", "where is the retry logic" recur across people and across weeks, and
the answer only changes when the graph does. Every repeat is paid for twice:
once in tokens on the LiteLLM bill, once in the seconds a developer waits.

Two questions had to be answered together, because the second only matters if
the first is yes:

1. Should answers be cached at all, given they can go stale?
2. If similarity matching is wanted, does that need a vector database?

## Decision

**Cache answers per squad, keyed on the project's index epoch, with a two-tier
lookup: exact first, then semantic. Store embeddings in the existing
PostgreSQL as bytes and score them in the gateway. Do not add a vector
database.**

**1. Staleness is solved by an epoch, not a TTL.** A new
`project_index_state` row records an integer epoch per (squad, project),
bumped by the indexer after every successful index. The cache key includes it,
so a reindex retires every answer computed from the previous graph in one
step, atomically, with no sweep job. A TTL is kept as a second bound for the
case where nothing is ever reindexed.

**2. Exact match first.** A normalised hash of the question is looked up
before anything else. The common case — the same question, verbatim — costs
one indexed row read and no embedding call at all.

**3. Semantic match second, over a filtered candidate set.** Entries are
filtered by squad, project, tool, epoch and embedding model, then scored by
cosine similarity in the gateway. A hit needs to clear a configurable
threshold; the default is deliberately high, because a wrong answer delivered
instantly is worse than a right answer delivered slowly.

**4. Embeddings come from LiteLLM.** The engine's embeddings are compiled into
its binary and unreachable ([docs/engine.md](../engine.md)), so the cache uses
the same proxy everything else does, with the squad's own virtual key. The
embedding model is an administrator setting.

**5. Squad isolation is structural.** Every row carries a squad, and every
lookup filters on it. There is no cross-squad cache, deliberately — a cached
answer contains as much source knowledge as the graph it came from, and the
tenancy model exists precisely to keep that inside one squad.

**6. No vector database, yet.** See below.

## Rationale

### Why not a vector database

The candidate set a similarity search actually runs over is small. It is
filtered first by squad, project, tool and epoch — and a single project's
distinct questions at one epoch number in the tens, not the millions. Scoring
a few hundred 1 536-dimension vectors in Python is well under a millisecond,
against an LLM call measured in seconds.

That reframes the choice. The question is not "which vector store is
fastest", it is "what does adding one buy at this size", and the answer is
nothing measurable.

**pgvector** was the strong candidate, because it needs no new service: it is
an extension in the PostgreSQL already deployed, keeping one datastore, one
backup, one set of credentials and one transaction boundary. It was rejected
*for now* rather than on the merits. Three costs, none of which buy anything
at the current scale:

- The extension has to exist. `CREATE EXTENSION vector` needs a privilege a
  managed instance may not grant, so the migration either fails on a database
  that would otherwise work, or becomes conditional — a schema that differs
  between deployments, which is the thing migrations exist to prevent.
- An indexed `vector(N)` column pins N. Changing the embedding model then
  needs a migration, which turns a setting into a deployment.
- The tests run against SQLite. A PostgreSQL-only column means the cache is
  either untested or tested differently from how it runs.

**Qdrant** (and Weaviate, Milvus) was rejected more firmly. A dedicated vector
service earns its place at millions of vectors, heavy payload filtering, or
hybrid search — none of which describe a per-squad answer cache. What it adds
immediately is a second stateful service to run, back up, secure and keep
consistent with the database that owns everything else, plus a second place a
squad's knowledge lives and a second thing to get the tenancy boundary right
in.

**When to revisit.** Concretely: when a single squad-and-project candidate set
regularly exceeds ~5 000 entries, or when cache lookup shows up at all in the
`repo_mcp_answer_cache_lookup_seconds` histogram against LLM latency. At that
point pgvector — not Qdrant — is the next step, and the embedding column is
already the only thing that changes.

### Why an epoch rather than a TTL alone

A TTL trades correctness for simplicity: pick it short and the cache barely
works, pick it long and answers describe code that no longer exists. Neither
failure is visible in the answer text, which is what makes it dangerous —
there is nothing in a stale answer that says it is stale.

An epoch makes invalidation exact and free. The indexer already knows the
moment a graph changed; recording it is one row.

### Why the threshold is high by default

A cache miss costs tokens and seconds. A false hit costs trust, and it is
almost impossible to notice: the answer is fluent, plausible and about a
different question. The asymmetry says to tune conservatively and let an
administrator lower it deliberately.

## Consequences

**Positive**

- Repeated questions cost one row read instead of thousands of tokens.
- A reindex invalidates exactly the answers that became stale, atomically.
- No new service, no new backup, no new credential, no new tenancy boundary.
- The cache is testable against SQLite, the same way everything else is.
- Cached answers never cross a squad boundary.

**Negative, accepted**

- **Answers are stored.** They contain synthesised knowledge of a squad's
  source, in a database whose other contents are mostly configuration. The
  squad boundary applies, but the blast radius of a database disclosure is now
  larger than it was. Mitigated by the boundary, by the TTL, and by
  `answer_cache.enabled`, which turns the whole thing off.
- **Similarity scoring runs in the gateway.** It is memory the gateway did not
  use before, bounded by the candidate cap, and it does not scale past the
  threshold named above.
- **The embedding call is not free.** A semantic lookup costs one embedding
  request before it can miss. Exact-match-first exists to keep that off the
  common path, and a squad that only ever asks novel questions pays it for
  nothing.
- **The epoch depends on the indexer writing it.** An index that succeeds
  without recording an epoch leaves answers cached against an old graph. The
  write is in the same path as the result, but it is a coupling that did not
  exist before.
- **Only `ask_codebase` is cached.** `explain_change_impact` depends on the
  working tree as well as the graph, and the cache key describes only the
  graph — a hit would answer about a diff that has since changed. It is
  excluded, so the more expensive of the two tools gets no benefit.

## Alternatives considered

**No cache; rely on LiteLLM's own caching.** Rejected. LiteLLM caches on the
exact request payload, which includes the graph evidence — so it only ever
hits when the graph is byte-identical, and it has no notion of a squad
boundary or of a reindex. It helps with retries, not with repeated questions.

**Cache in memory in the gateway.** Rejected: it dies with the pod, is not
shared between replicas, and grows without a bound anybody set. The database
is already there and already the thing both services agree on.

**A TTL with no epoch.** Rejected — see above. It cannot distinguish "old" from
"wrong", and neither can the reader of the answer.

**Cache the graph evidence rather than the answer.** Tempting, since evidence
is the expensive part of the payload. Rejected: evidence is cheap to recompute
(the engine is local and fast) and the expensive part is the model call, which
this would not avoid.

**Share the cache across squads for common questions.** Rejected outright. It
would need a notion of a question whose answer is not squad-specific, which
does not exist, and the failure mode is one squad reading another's code
through a cache hit.
