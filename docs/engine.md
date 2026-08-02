# The indexing engine

repo-mcp does not parse source code itself. It embeds a third-party engine —
`codebase-memory-mcp`, MIT licensed, attributed in [NOTICE](../NOTICE) — which
turns a repository into a knowledge graph and answers structural queries
against it. Everything else in this project is built around it.

**This is the one page that talks about the engine's internals.** It exists
because the engine's design decides several of ours, and those decisions are
easier to review when the reasons are written down. Elsewhere in the docs the
engine is treated as a component with a known contract.

Every claim below is verified against the engine's source rather than its
documentation, so a reviewer can check the reasoning instead of taking it on
trust. File references point into the engine's own tree; see the NOTICE file
for where that lives.

## 1. stdio is the only transport

`src/mcp/mcp.h`:

> Implements JSON-RPC 2.0 over stdio with the MCP tool calling protocol.

`src/main.c` help output:

```
codebase-memory-mcp              Run MCP server on stdio
codebase-memory-mcp cli [--progress] [--json] <tool> [args]
```

There is no HTTP, SSE or streamable-HTTP MCP transport. Any network client
needs a stdio bridge, and that bridge is ours to build — it lives in
`gateway/app/cbm.py`.

Messages are line-delimited: the parser signature is
`cbm_jsonrpc_parse(const char *line, ...)`. Framing is therefore trivial —
one JSON object per line.

## 2. The built-in HTTP server cannot be exposed

`src/ui/httpd.c`:

```c
addr.sin_addr.s_addr = htonl(0x7F000001); /* 127.0.0.1 */
```

`src/ui/http_server.c` states it *"binds to 127.0.0.1 only"* and its CORS
check accepts localhost origins only. This server exists to render the 3D
graph UI; it is not an API. The bind address is compiled in and no
configuration changes it.

**Consequence:** the web UI in our roadmap has to be built on our own query
API. The upstream visualiser cannot be re-hosted for multiple users.

## 3. The daemon speaks owner-only local IPC

`src/daemon/ipc.h`:

> Unix builds use owner-only Unix-domain sockets and advisory file locks.

The coordination daemon is per account and by design refuses connections from
anything that is not local and not the same user. Multi-tenancy therefore
means separate OS users or separate containers — two squads cannot share one
daemon.

## 4. Exact-build admission barrier

`src/daemon/version_cohort.h` — *"Crash-safe exact-build admission across CBM
processes."* Every live CBM process must agree on version, build, coordination
ABI and canonical cache root; a mismatch fails with
`CBM_VERSION_COHORT_CONFLICT`.

**Consequence:** one pinned image everywhere, and rolling updates must replace
all of a tenant's processes together rather than mixing versions. See
[deployment.md](deployment.md).

## 5. Restricted tool profiles — a control designed for wrappers

`src/mcp/mcp.c`, `mcp_tool_allowed()` implements a fail-closed allowlist:

| Profile | Tools exposed |
| --- | --- |
| `--tool-profile=analysis` | `search_graph`, `query_graph`, `trace_path`, `get_code_snippet`, `get_graph_schema`, `get_architecture`, `search_code`, `list_projects`, `index_status`, `check_index_coverage`, `detect_changes` |
| `--tool-profile=scout` | `search_graph`, `trace_path`, `get_code_snippet`, `get_architecture`, `list_projects`, `index_status`, `check_index_coverage` |
| *(default)* | all 15 tools |

In a restricted profile `index_repository`, `delete_project`, `manage_adr` and
`ingest_traces` are neither advertised by `tools/list` nor callable, and
`cbm_mcp_tool_profile_allows_http()` disables the HTTP UI entirely. An unknown
or malformed value fails closed with `-1`.

This is the second of our three authorization layers, enforced inside the
engine process rather than by the gateway.

## 6. Fifteen tools

From `TOOLS[]` in `src/mcp/mcp.c`:

```
index_repository  search_graph      query_graph        trace_path
get_code_snippet  get_graph_schema  get_architecture   search_code
list_projects     delete_project    index_status       check_index_coverage
detect_changes    manage_adr        ingest_traces
```

There is no separate `semantic_query` tool; semantic search is folded into
`search_graph` and tuned with `CBM_SEMANTIC_ENABLED` and
`CBM_SEMANTIC_THRESHOLD`.

## 7. One SQLite file per project, flat in the cache directory

`src/store/store.c`, `cbm_store_open()`:

```c
const char *cdir = cbm_resolve_cache_dir();
snprintf(path, sizeof(path), "%s/%s.db", cdir, project);
```

Project names are validated by `cbm_validate_project_name()` against path
traversal.

**Consequences, both load-bearing:**

- The cache directory *is* the isolation unit. `list_projects` returns every
  project in it, so squad isolation requires a separate `CBM_CACHE_DIR` per
  squad.
- `CROSS_*` edges are only created between projects in the *same* store. That
  puts isolation and cross-repository visibility in direct tension — resolved
  by the two-layer model in [ADR-0002](adr/0002-tenancy-model.md).

## 8. No LLM, and embeddings cannot be redirected

Every environment variable found in `src/`:

```
CBM_ALLOWED_ROOT        CBM_CACHE_DIR          CBM_CYPHER_MAX_DEPTH
CBM_DIAGNOSTICS         CBM_DISABLE_LSP_CROSS  CBM_DOWNLOAD_URL
CBM_DUMP_VERIFY_MIN_RATIO  CBM_HOOK_DEADLINE_MS  CBM_INDEX_*
CBM_LOG_FORMAT          CBM_LOG_LEVEL          CBM_MAX_FILE_BYTES
CBM_MCP_MAX_DEPTH       CBM_MEM_*              CBM_PROFILE
CBM_RETAIN_*            CBM_SEMANTIC_ENABLED   CBM_SEMANTIC_THRESHOLD
CBM_SQLITE_MMAP_SIZE    CBM_UI_MAX_RENDER_NODES
CBM_WATCHER_PRUNE_GRACE_S  CBM_WORKERS
```

There is no API base URL, API key, model name or embedding endpoint. The
embedding model is compiled into the binary.

**Consequence:** LiteLLM cannot be plugged in *underneath* CBM. It belongs
*above* it, in the gateway. This is a feature rather than a limitation: graph
construction stays deterministic and costs no tokens, and the model is only
involved where synthesis is genuinely required.

## 9. `CBM_ALLOWED_ROOT`

`src/mcp/mcp.c` confines `index_repository` to the given directory, falling
back to the process-wide environment variable when no per-server policy is
set. Upstream documents it for untrusted-caller and agentic-wrapper
deployments — precisely this one.

## 10. No history

CBM stores the *current* graph. `detect_changes` compares a working tree
against a base branch using git; it does not read stored snapshots. Any
"what did this look like last month" capability has to be built on retained
artifacts. See [ADR-0004](adr/0004-graph-history.md).

## 11. Licence

MIT. Wrapping, containerising and redistributing it internally or publicly is
permitted.

## Summary

| Need | CBM | Built here |
| --- | --- | --- |
| Repository parsing and graph construction | yes | — |
| Change impact (`detect_changes`) | yes | CI and pull request integration |
| Incremental indexing | yes | webhook and schedule triggers |
| Repository discovery across an org | no | provider connectors |
| Network access | no | stdio-to-HTTP gateway |
| Authentication | no | OIDC/JWT via LDAP federation |
| Authorization, squads, roles | no | ACL, role capabilities, per-tenant stores |
| Audit logging | no | gateway |
| Graph history | no | retained artifacts |
| LLM reasoning | no, by design | LiteLLM-backed composite tools |
