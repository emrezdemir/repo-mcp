# Scaling

Two constraints shape every topology here, both verified in
[engine.md](engine.md):

1. **The engine's cache is SQLite in WAL mode.** Many readers, one writer, on
   a POSIX filesystem. Not on NFS.
2. **The engine enforces an exact-build admission barrier.** Every process
   sharing a cache root must be the same build, so upgrades replace all of a
   tenant's processes at once.

Everything below follows from those.

## Who writes what

| Component | Cache root | Repository working copies |
| --- | --- | --- |
| Indexer | writes | writes (clone, fetch, checkout) |
| Gateway | reads | reads |

The gateway's volume is still mounted read-write, and that is deliberate:
SQLite in WAL mode creates `-wal` and `-shm` files in order to *read*, and the
engine keeps its own configuration and logs under the cache root. A read-only
mount makes every query fail with `SQLITE_READONLY`.

What actually prevents the gateway from mutating anything is the tenant's tool
profile — `analysis` and `scout` have no write tools at all, enforced inside
the engine process.

## Topologies

### 1. Single node — start here

```
┌──────────────── one node ────────────────┐
│  gateway ×1        indexer ×1            │
│      └──── shared PVC (RWO) ────┘        │
└──────────────────────────────────────────┘
```

Both pods on one node, one ReadWriteOnce volume. Simple, correct, and enough
for a few hundred developers: graph queries answer in milliseconds and the
gateway is not the bottleneck.

```yaml
gateway: { replicaCount: 1, autoscaling: { enabled: false } }
indexer: { replicaCount: 1 }
persistence:
  cache: { accessMode: ReadWriteOnce, size: 100Gi }
```

Scale *up* before scaling out. `indexer.config.concurrency` with more memory
buys more than a second replica would.

### 2. Shared filesystem — several gateway replicas

```
   gateway ×N ──┐
                ├── RWX volume (block-backed) ── indexer ×1
                ┘
```

Requires `ReadWriteMany` on a filesystem where SQLite WAL locking is reliable:
CephFS, Portworx, Longhorn RWX, or a cloud file service backed by real POSIX
locks. **Not NFS** — WAL locking there is unreliable and will corrupt stores.

The chart refuses to render an HPA unless `accessMode` is `ReadWriteMany`,
because the alternative is a silent data-loss configuration.

```yaml
gateway:
  autoscaling: { enabled: true, minReplicas: 2, maxReplicas: 10 }
persistence:
  cache: { accessMode: ReadWriteMany, storageClass: cephfs }
```

Every tenant must use a read-only tool profile in this topology. With
`tool_profile: all`, two gateway replicas could both try to index the same
project and contend on the engine's mutation lock.

### 3. Synced replicas — the horizontal answer

```
  indexer ×1  ──writes──▶  cache PVC
      │
      └── publishes graph.db.zst ──▶ object storage
                                          │
              gateway ×N, each with its own local PVC ◀── syncs
```

The indexer already writes `.codebase-memory/graph.db.zst` when
`persistence: true`. Uploading those artifacts and having each gateway replica
keep a local copy removes shared storage from the picture entirely: replicas
scale freely, each reading a local disk, and a replica failure loses nothing.

The cost is staleness — a replica is as fresh as its last sync.

This topology is designed but **not implemented**; the sync sidecar is on the
[roadmap](roadmap.md). Until then, use topology 1 or 2.

## Why the indexer stays at one replica

The job queue and its per-project locks live in the process. Two replicas
means two pods can pick up the same project and block on the engine's mutation
lock, wasting a worker slot for the length of an index run.

Horizontal indexing needs a shared queue (Redis or NATS) with per-project
leases that survive a restart. That is on the roadmap. Until then the chart
warns when `indexer.replicaCount > 1`, and you should raise
`indexer.config.concurrency` instead.

## Upgrades

Both workloads use the `Recreate` strategy rather than `RollingUpdate`. During
a rolling update, old and new pods would briefly share a cache root with
different engine builds, and the version cohort barrier fails that with
`CBM_VERSION_COHORT_CONFLICT`.

Pin `engine.version` rather than tracking `latest`, so an upstream release
cannot change the build under a running deployment.

## Capacity planning

**Storage.** Graph stores run roughly 5–15% of source size, varying by
language. Working copies are cloned with `--filter=blob:none`, so they are far
smaller than full clones. Measure with one connector before sizing for the
organisation.

**The first pass is the expensive one.** Indexing an entire organisation from
scratch is hours of work; steady-state incremental runs are seconds to minutes.
Onboard one connector in `mode: fast`, measure, then widen.

**Memory.** Indexing is RAM-first and releases memory afterwards, so the peak
during a run is what sizes the limit. Cap it explicitly with
`CBM_MEM_BUDGET_MB` and set `CBM_WORKERS` to match the CPU limit — the engine
otherwise sizes its pool from the host, not the cgroup.

**Gateway memory** scales with the number of *active* tenants, since each
holds a live engine process. `CBM_IDLE_TIMEOUT_S` (default 900s) is what
bounds it; lower it if many tenants are occasional users.

## What to watch

| Metric | Meaning |
| --- | --- |
| `repo_mcp_index_queue_depth` | Rising steadily means indexing cannot keep up with pushes. |
| `repo_mcp_index_duration_seconds` | A jump usually means a repository grew, or `mode` changed. |
| `repo_mcp_tool_duration_seconds` | The p99 is the developer-visible latency. |
| `repo_mcp_cbm_sessions` | Live engine processes — the gateway's real memory driver. |
| `repo_mcp_cbm_restarts_total{reason="restart"}` | Repeated restarts mean calls are timing out. |
| `repo_mcp_index_jobs_total{outcome="timeout"}` | Raise the index timeout, or move that repository to a lighter mode. |
| `repo_mcp_llm_calls_total{outcome!="ok"}` | Model backend trouble, not graph trouble. |

Alert on queue depth and on the timeout counters first. Everything else is
diagnostic.
