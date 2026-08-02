# Deployment

## Local evaluation

```bash
cd deploy
cp tenants.example.yaml tenants.yaml
cp scan.example.yaml scan.yaml
export LITELLM_MASTER_KEY=$(openssl rand -hex 24)
export GITHUB_TOKEN=ghp_...            # a read-only token for discovery
export WEBHOOK_SECRET_GITHUB=$(openssl rand -hex 24)
docker compose up --build
```

| Service | URL |
| --- | --- |
| Gateway (MCP) | http://localhost:8080/mcp |
| Indexer | http://localhost:8082 |
| Keycloak | http://localhost:8081 |
| LiteLLM | http://localhost:4000 |

Trigger the first discovery pass:

```bash
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

## Keycloak and LDAP

1. Create a realm (`engineering` in the example configuration).
2. Add **User federation → LDAP** with a read-only bind account. Set the
   users DN, the username attribute (`sAMAccountName` for Active Directory,
   `uid` for OpenLDAP) and enable periodic sync.
3. Add **Mappers → group-ldap-mapper** so directory groups become Keycloak
   groups.
4. Create a client `repo-mcp`, then add a **Group Membership** mapper with
   token claim name `groups` and *Full group path* switched **off** — the
   gateway strips a leading slash, but plain names keep the configuration
   readable.
5. Create a client scope so the `groups` claim is included in access tokens.
6. Theme the login page if you want the platform's own branding; it is still
   LDAP behind it.

For CI, create a service account client with client credentials and put it in
whichever groups grant the scope its pipelines need.

Verify a token before wiring agents up:

```bash
TOKEN=$(curl -s -d grant_type=password -d client_id=repo-mcp \
  -d username=alice -d password=... \
  http://localhost:8081/realms/engineering/protocol/openid-connect/token | jq -r .access_token)

curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'X-Tenant: payments' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq
```

## Webhooks

Point each repository or organisation at the indexer:

| Provider | URL | Secret header |
| --- | --- | --- |
| GitHub | `POST /webhook/github` | `X-Hub-Signature-256`, secret in `WEBHOOK_SECRET_GITHUB` |
| GitLab | `POST /webhook/gitlab` | `X-Gitlab-Token`, secret in `WEBHOOK_SECRET_GITLAB` |
| Bitbucket | `POST /webhook/bitbucket` | `X-Hub-Signature`, secret in `WEBHOOK_SECRET_BITBUCKET` |

Only push events on the default branch are indexed centrally. Branch
deletions and pushes to other refs are acknowledged and ignored.

## CI integration

```yaml
- name: Refresh the code graph
  run: |
    curl -fsS -X POST "$REPO_MCP_INDEXER/trigger" \
      -H "Authorization: Bearer $CI_TRIGGER_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "{\"repository\": \"$GITHUB_REPOSITORY\", \"sha\": \"$GITHUB_SHA\"}"
```

## Production notes

**One pinned engine build.** CBM enforces an exact-build admission barrier
across processes sharing a cache root. Pin `CBM_VERSION` in the image and
upgrade a tenant's processes together — `Recreate`, not `RollingUpdate`. A
half-upgraded tenant fails with a version cohort conflict.

**Never expose the engine.** CBM has no authentication. The gateway is the only
ingress; `CBM_ALLOWED_ROOT` is the backstop, not the control.

**Storage.** Stores are plain files at `<cache>/tenant/<squad>/<project>.db`,
so back-up and tenant migration are file copies. Use a filesystem that handles
SQLite WAL correctly — local disk or a block volume, not NFS.

**Resource limits.** Set `CBM_WORKERS` and `CBM_MEM_BUDGET_MB` to match pod
limits. Indexing is RAM-first and releases memory afterwards, so the peak is
what matters for sizing.

**Sizing the first run.** Indexing an entire organisation the first time is the
expensive moment; steady-state incremental runs are far cheaper. Start one
connector with `mode: fast`, measure, then widen.

**Secrets.** Provider tokens, webhook secrets and LiteLLM keys all come from
the environment. Nothing belongs in `tenants.yaml` or `scan.yaml` — both are
meant to be readable in review and safe to commit.
