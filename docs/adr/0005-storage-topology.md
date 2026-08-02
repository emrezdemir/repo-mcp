# ADR-0005: One writer, many readers, on a POSIX filesystem

- **Status:** Accepted
- **Context:** How the graph stores are shared between the indexer and the
  gateway, and what that permits when scaling out.

## Context

The engine keeps each project's graph in its own SQLite database, in WAL mode,
under a cache directory ([engine.md §7](../engine.md)).
Two components touch it: the indexer writes, the gateway reads.

SQLite in WAL mode supports many concurrent readers and a single writer — but
only where file locking is correct. It is not correct over NFS, and getting
that wrong corrupts stores rather than producing an error.

## Decision

**The indexer is the only writer.** The gateway reads. Both mount the cache
root read-write, and the write restriction is enforced by the tenant's tool
profile inside the engine process rather than by the mount.

The supported topologies are, in order of preference:

1. **Single node, ReadWriteOnce.** The default. One gateway, one indexer, one
   volume.
2. **ReadWriteMany on a block-backed filesystem.** Several gateway replicas.
   Requires every tenant to use a read-only tool profile. NFS is not
   supported.
3. **Synced replicas.** The indexer publishes `graph.db.zst` artifacts; each
   gateway replica keeps a local copy. Designed, not yet implemented.

The Helm chart refuses to render an HPA unless the access mode is
`ReadWriteMany`.

## Rationale

**Why not mount the gateway's volume read-only,** which would be the obvious
way to enforce a single writer? Because it does not work. SQLite creates
`-wal` and `-shm` files in order to *read* a WAL database, and the engine
writes its own configuration and logs under the cache root. A read-only mount
turns every query into `SQLITE_READONLY`. Enforcing the restriction through
the tool profile — a mechanism the engine already implements and fails closed
on — is both effective and honest about what the filesystem is doing.

**Why fail the HPA rather than warn.** A gateway replica scheduled without
access to the graph stores does not fail loudly; it answers queries with an
empty graph, which looks like a code problem rather than a deployment problem.
Failing at template time costs one confused minute; the alternative costs an
afternoon.

**Why `Recreate` rather than `RollingUpdate`.** The exact-build admission
barrier means old and new pods sharing a cache root during a rollout is
exactly the state the engine refuses to be in. Brief unavailability is
preferable to a rollout that half-succeeds.

## Consequences

**Positive**

- The default topology is simple and hard to misconfigure.
- Backup and tenant migration are file copies.
- The single-writer rule makes indexing failures easy to attribute.

**Negative, accepted**

- Gateway horizontal scaling needs storage most clusters do not have by
  default. Topology 3 removes that requirement but is not built yet.
- `Recreate` means a short gap on every upgrade. For an internal developer
  tool that is acceptable; for anything user-facing it would not be.
- The read-write mount means a bug in the gateway *could* write to the cache.
  The tool profile is what prevents it, and it is a fail-closed allowlist
  inside a separate process — but it is one mechanism rather than two.

## Alternatives considered

**Give each gateway replica its own indexer.** Rejected: every replica would
reindex the same repositories, which is the local-machine waste the whole
project exists to remove.

**Put the graph in a networked database instead of SQLite.** Rejected — that
is a fork of the engine ([ADR-0001](0001-wrap-dont-fork.md)), and a large one.

**Allow NFS with a warning.** Rejected. The failure mode is silent corruption
discovered days later. Some configurations should be refused rather than
documented.
