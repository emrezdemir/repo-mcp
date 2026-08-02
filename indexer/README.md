# repo-mcp indexer

Discovers repositories across GitHub, GitLab and Bitbucket, and keeps their
knowledge graphs current — from push webhooks, a periodic rescan, or an
explicit CI trigger.

Part of [repo-mcp](../README.md); see [../docs/architecture.md](../docs/architecture.md)
for how it fits together.

## Layout

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app: webhooks, `/trigger`, `/rescan`, `/repos`, `/metrics` |
| `app/providers.py` | Repository discovery per provider |
| `app/repos.py` | Scan configuration, tenant routing, project naming |
| `app/webhooks.py` | Signature verification and payload normalisation |
| `app/worker.py` | The job queue and the engine CLI invocation |
| `app/metrics.py` | Prometheus instrumentation |

## Running it

```bash
pip install -e '.[dev]'
pytest

# From the repository root:
../scripts/dev.sh indexer
```

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /webhook/{github,gitlab,bitbucket}` | Verified push events |
| `POST /trigger` | Index one repository at one commit (CI) |
| `POST /rescan` | Rediscover everything and queue a full pass |
| `GET /repos` | What is currently in scope |
| `GET /healthz` | Liveness and queue depth |
| `GET /metrics` | Prometheus exposition |

`/trigger` and `/rescan` require `Authorization: Bearer $CI_TRIGGER_TOKEN`.

## Why not the engine's own watcher

codebase-memory-mcp ships a git-polling watcher. Centrally that becomes N
repositories polled forever, with latency nobody can predict. Webhook- and
schedule-driven indexing is deterministic, measurable, and free while idle.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SCAN_CONFIG` | Path to `scan.yaml` |
| `GITHUB_TOKEN`, `GITLAB_TOKEN`, `BITBUCKET_APP_PASSWORD` | Discovery credentials |
| `WEBHOOK_SECRET_{GITHUB,GITLAB,BITBUCKET}` | Signature verification |
| `CI_TRIGGER_TOKEN` | Guards `/trigger` and `/rescan` |
| `INDEX_CONCURRENCY` | Concurrent jobs in this process |
| `RESCAN_INTERVAL_S` | Periodic full pass |

One replica only — the queue and its per-project locks are in-process. See
[../docs/scaling.md](../docs/scaling.md).
