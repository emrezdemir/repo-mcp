# The web interface

This is upstream's `graph-ui`, adopted rather than rewritten, and pointed at
this platform.

- **Upstream:** https://github.com/DeusData/codebase-memory-mcp, `graph-ui/`
- **Adopted from:** `d6be58ef9d43c574a2d1b0827ecc1e3c4846f0fe`
- **Licence:** MIT — see [NOTICE](../../NOTICE)

React 19, Three.js through @react-three/fiber, Tailwind 4, built with Vite.

## What changed, and why

The transport. Upstream `src/api/rpc.ts` talked to the engine's own loopback
server at `POST /rpc`. It now talks to `POST /mcp`: the same JSON-RPC protocol
and the same tool names, but through the gateway, so every call carries the
signed-in user's token and their squad and is checked against role
capabilities, the project allowlist and the engine's tool profile.

| Upstream | Here | Why |
| --- | --- | --- |
| `POST /rpc` | `POST /mcp` with a token and `X-Tenant` | Same protocol; authorization is the gateway's |
| `GET /api/layout` | the same, proxied and authorized | 860 lines of C computing a 3D layout — not worth reimplementing |
| `GET /api/project-health` | `index_status` tool | An engine tool, so it goes through the ACL |
| `GET`/`POST /api/adr` | `manage_adr` tool | Behind the MANAGE_ADR capability |
| `POST /api/index` | `index_repository` tool | Behind TRIGGER_INDEX; the path must be under the squad's root |
| `GET /api/index-status` | `index_status` tool | |
| `DELETE /api/project` | `delete_project` tool | Behind ADMINISTER |
| `GET /api/repo-info` | `list_projects`, which already carries it | One request instead of two |
| `GET /api/browse` | removed | Filesystem browsing has no place on a shared platform |
| `GET /api/logs`, `/api/processes` | removed with the Control tab | Single-machine surfaces |
| — | sign-in, squad picker, admin console | This platform has identity and tenancy; a local tool does not |

## Working on it

```bash
npm install
npm run dev            # :5173, proxying /mcp, /api and /admin to the gateway
npm run build          # -> dist/, which the image copies to gateway/app/ui/
npm test
```

`scripts/dev.sh gateway` must be running for the proxy to have anything to talk
to. The graph needs the build of the engine that includes the interface — the
one without it answers `--ui requested, but this binary was built without the
embedded UI` and the graph page says so.

## Taking upstream changes

`graph-ui` is 60 files and moves independently of the engine. To pull a newer
version, diff it against the commit named above, apply what is wanted, and
re-check the table: anything upstream adds that calls `/api/…` needs a
decision about whether it belongs on a shared platform at all.
