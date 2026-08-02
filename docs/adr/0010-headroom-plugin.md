# ADR-0010: Headroom is a pinned upstream service, not vendored code

- **Status:** Accepted
- **Context:** Prompt evidence sent to the model is large, and
  [Headroom](https://github.com/headroomlabs-ai/headroom) compresses exactly
  that kind of content. The question was how to adopt it without inheriting it.

## Context

`ask_codebase` sends up to 20 000 characters of graph evidence per call, most
of it JSON. `explain_change_impact` sends an impact set of the same shape.
That is precisely what Headroom's JSON path is built for, and it reports the
largest savings on structured content.

Headroom ships three ways: a library, an OpenAI-compatible proxy on port 8787,
and an MCP server. It is Apache-2.0, and it moves — the point of adopting it
is to keep getting its improvements, not to freeze a copy.

Two constraints shaped the answer. It has to be **updatable**: a vendored
snapshot is a fork nobody chose to maintain. And it has to be **removable**:
anything sitting between a question and its answer must be possible to take
out without unpicking the rest of the platform.

## Decision

**Run Headroom as its own pinned container, in front of LiteLLM, enabled by a
setting. Vendor nothing.**

```
gateway ──chat/completions──▶ headroom ──▶ LiteLLM ──▶ model
        └─embeddings────────────────────▶ LiteLLM ──▶ model
```

**1. The proxy, not the library or the MCP server.** The library would put
Headroom's release cadence inside our dependency graph and its failures inside
our request path. The MCP server would put it beside the engine, where it has
nothing to compress. The proxy is a URL, and a URL is a thing that can be
swapped, pinned and removed.

**2. Updating it is bumping a tag.** `HEADROOM_VERSION` in the Compose stack,
`headroom.image.tag` in the chart. That is the same mechanism the platform's
own images use ([ADR-0008](0008-environments-and-promotion.md)) and it
supports an internal mirror the same way the engine download does.

**3. Off by default, and one setting to turn it off.**
`headroom.enabled` is false unless an administrator sets it. Turning it off
sends the gateway straight back to LiteLLM, with nothing else to undo.

**4. An unreachable Headroom does not fail a tool call.** The gateway retries
once against LiteLLM directly and logs it. A compression layer that can take
down question-answering is worse than no compression layer.

**5. Embeddings never go through it.** The answer cache
([ADR-0009](0009-answer-cache.md)) embeds a question to find a similar one.
Compressing that text first would move the vector, so two identical questions
could embed differently depending on what Headroom decided — a cache whose
keys drift. Embeddings go straight to LiteLLM.

**6. It only ever sees prompts, never tool results.** Raw engine output —
`get_code_snippet` included — is returned to the client without passing
through any model, so it cannot reach Headroom by construction. That is a
property of where the proxy sits, not a rule anyone has to remember.

## Rationale

**Why not vendor it.** Copying the code in makes every future improvement a
merge, and every upstream fix a decision someone has to notice. Within two
releases the copy is a fork. The user's requirement — updatable, not "took it
once and used it" — is the same conclusion from the other direction.

**Why in front of LiteLLM rather than behind it.** LiteLLM is where keys,
budgets and per-squad attribution live; it must stay the last hop before the
model. Compression belongs upstream of it, on the content, not downstream of
it, on the routing.

**Why a setting rather than a deployment choice alone.** Compression changes
what the model sees, so its effect is visible in answer quality. Being able to
turn it off from the admin API, without a redeploy, is what makes an A/B
comparison — or an incident — a two-minute operation.

**Why the fallback is silent to the caller but loud in the logs.** The caller
asked a question about a codebase; whether a compression proxy was involved is
not their concern. The operator's concern is exactly that, so it is a log line
and a metric label.

## Consequences

**Positive**

- Fewer tokens on the two tools that send the most, without touching them.
- Upgrading is a tag bump, and rolling back is the previous tag.
- One setting removes it from the path entirely.
- The answer cache's keys stay stable, because embeddings bypass it.
- No new code to maintain: the integration is a base URL and a fallback.

**Negative, accepted**

- **A third party now sees prompt content.** Self-hosted, inside the same
  trust boundary, but it is one more process holding a squad's graph evidence
  in memory, and one more image to keep patched. Squads that cannot accept
  that leave `headroom.enabled` false, which is the default.
- **Compression can degrade an answer, quietly.** A dropped detail does not
  announce itself; the answer is simply less specific. There is no automated
  check for this, and there cannot easily be one — the mitigation is that it
  is off by default and trivially reversible.
- **Another service to run.** One more container, one more health check, one
  more thing that can be down. The fallback keeps that from being an outage,
  but it is not free.
- **An unverified upstream contract.** Headroom's own upstream routing is
  configured by its environment, which is documented by Headroom and not by
  us. We point at a URL and pass its variables through untouched, so a change
  in its configuration is an operator's problem rather than a code change —
  but it does mean this integration is only as stable as that interface.
- **Savings are unmeasured here.** The upstream figures are upstream's. The
  gateway records request counts and durations by route, which is enough to
  compare, but nobody has run that comparison yet.

## Alternatives considered

**Vendor the compression code.** Rejected — see above. It converts an
Apache-2.0 dependency into an unmaintained fork.

**Use the Python library in the gateway.** Rejected: it puts a model-serving
dependency, its ONNX runtime and its release cadence into a process whose job
is authorization and routing, and a library failure becomes a request failure
with no fallback boundary to catch it.

**Route everything, including embeddings, through it.** Rejected — it would
make the answer cache's embedding depend on a compression decision, so the
same question could land in two places in vector space.

**Compress in the gateway ourselves, with our own summariser.** Rejected: it
is a second LLM call to save the first one's tokens, and it is a whole
research problem to do well. Someone else is doing it well.

**Enable it by default.** Rejected. It changes what the model is told, on a
platform whose entire value is answers people trust. That is an administrator's
decision to make knowingly.
