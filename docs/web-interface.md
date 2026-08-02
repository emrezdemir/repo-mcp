# The web interface

The gateway serves a browser interface at `/ui`. It exists so that the graph
can be looked at by a person, and so that the platform can be configured
without a terminal — not as a second product with its own rules.

![The graph](images/ui-graph.png)

## What it is, and what it deliberately is not

Every question the interface asks about a codebase goes to `POST /mcp` as
ordinary JSON-RPC, with the signed-in user's own token. It has no read path of
its own. Anything the browser can do, an MCP client can do, authorized and
audited by exactly the same code.

That is the whole design constraint. A second read API beside the first would
be a second place for the tenancy rules to be wrong, and the two would drift.

Two endpoints exist that MCP has no answer for:

| Endpoint | Answers |
| --- | --- |
| `GET /api/auth` | How to sign in: the redirect flow, the token box, or development mode. Public, because it is answered before anyone is signed in. |
| `GET /api/session` | Who the caller is here: which squad, which role, which tools. Used to decide which buttons to show. |
| `GET /api/ui-config` | Presentation only — the interface's language, if an installation pins one. Public, because it is read while rendering the sign-in screen. |
| `GET /api/layout` | The 3D layout, proxied from this squad's engine after the same authorization a tool call gets. |

`/api/session` is a convenience, not a permission. Getting it wrong would show
a button that then fails with a clear refusal — the authorization decision is
made in `mcp.py`, on the request, every time.

It reports exactly what `tools/list` would: both call `smart_tools_for`, so a
composite tool is offered here only when it would actually be answered there.

## What happens when the platform refuses

A control the platform is certain to refuse is rendered disabled, with the
reason on it, rather than hidden — an administrator debugging permissions
needs something to look at. A refusal that does arrive is shown in the
platform's own words, because those name what is missing:

```
'manage_adr' is not available in this session (role: lead, squad: payments)
no access to project 'acme-checkout-web' (allowed: acme-ledger, acme-payments-*)
```

Nothing fails silently. A save that appears to work and did not is worse than
one that says so.

The administrative console is the exception: it talks to `/admin/*`, the same
routes `repo-mcp-admin` uses, with a separate local session. See
[administration.md](administration.md).

## Signing in

The screen matches the deployment, because it asks the platform what the
deployment is rather than assuming at build time.

![Signing in](images/ui-signin.png)

**Through the identity provider.** When `oidc.issuer` and
`oidc.browser_client_id` are both set, the interface runs Authorization Code
with PKCE:

1. It fetches `<issuer>/.well-known/openid-configuration` to find the
   authorization and token endpoints.
2. It generates a verifier, stores it in `sessionStorage`, and redirects to
   the provider with the SHA-256 challenge.
3. The provider authenticates the person and redirects back to `/ui` with a
   code.
4. The interface exchanges the code, sending the verifier, and receives an
   access token.

There is no client secret; a public client cannot keep one, and PKCE is what
replaces it. The gateway is not in the flow at any point — it verifies the
resulting token on `/mcp` exactly as it verifies an MCP client's.

**With a token.** Without a browser client the token box remains, and it stays
available alongside the redirect. Pasting the token an MCP client is using is
the quickest way to find out why that client is being refused.

**In development.** `DEV_INSECURE_AUTH` accepts one static token and verifies
nothing. The sign-in screen says so, in those words. A screen that looked the
same as a real one would be actively misleading.

### What is stored, and where

The access token, the refresh token and the expiry go in `sessionStorage` and
nowhere else — not `localStorage`, not a cookie. Closing the tab ends the
session, and nothing is written to disk. An expiring token is renewed just
before the request that would otherwise have failed, so a session in use does
not expire under someone.

### Registering the client

The bundled Keycloak already has one. `deploy/keycloak/repo-mcp-realm.json` is
imported on first start and carries a `repo-mcp-web` public client with PKCE,
the group and audience mappers, and the groups the example squads refer to.
Create a user and point the platform at it:

```bash
scripts/keycloak-user.sh ada --name "Ada Lovelace" --group squad-payments
repo-mcp-admin set oidc.issuer http://localhost:8081/realms/repo-mcp
repo-mcp-admin set oidc.browser_client_id repo-mcp-web
```

For an existing Keycloak, a client for the interface needs:

| Setting | Value |
| --- | --- |
| Client ID | whatever you set `oidc.browser_client_id` to, for example `repo-mcp-web` |
| Client authentication | off — this is a public client |
| Standard flow | on |
| Direct access grants | off |
| Valid redirect URIs | `https://repo-mcp.example.com/ui` |
| Web origins | `https://repo-mcp.example.com` |
| Proof Key for Code Exchange | `S256` |

The group membership claim has to reach the token under the name
`oidc.groups_claim` expects (`groups` by default). Keycloak renders groups as
`/squad-payments`; the gateway strips the leading slash.

Then, from a terminal or from the console:

```bash
repo-mcp-admin set oidc.browser_client_id repo-mcp-web
```

Web origins is the setting people miss. Without it the browser's request to
the token endpoint is refused by CORS, and the sign-in fails after the
redirect rather than before it.

## The pages

### Projects

What this squad has indexed: node and edge counts per project, its health, and
its ADR. Selecting one opens the graph.

![Projects](images/ui-projects.png)

Adding a project is not offered here. A repository is discovered by a
connector and cloned by the indexer under the squad's own root — there is no
path a person should be choosing by hand on a shared platform, and the gateway
refuses one outside that root regardless.

### Graph

The project's graph in 3D, drawn with Three.js.

The layout is not computed in the browser. The engine computes it in C,
reading the graph database directly, and serves it on a loopback port; the
gateway authorizes the request — the caller's token, their squad, the
`READ_GRAPH` capability and the squad's project allowlist — and only then
proxies to that port. Reimplementing 860 lines of C in Python would be slower
and would drift from what the engine knows.

That port has no authentication of its own. It binds `127.0.0.1`, the gateway
chooses it, and it is never published, so the trust boundary is the one the
stdio pipe already has: the engine process is trusted, and reaching it is not.

Filtering is by node type, relationship type, folder, and by status — dead
code, entry points, tests. The node budget is the user's to raise; the count
actually drawn is always stated next to the total.

This needs the engine build that includes the interface
(`CBM_EDITION=-ui`, the default). Without it the graph page says so, and the
rest of the interface works.

### Ask

A question in words, answered from the graph.

![Ask](images/ui-ask.png)

`ask_codebase` runs `get_architecture` and `search_graph` first and answers
from what they returned, citing the qualified name of every symbol it
mentions. The model is never asked to guess the graph — which is why the
answer is checkable, and why a question about a project nobody has indexed
gets "the evidence is insufficient" rather than an invention.

It needs three things at once: a model backend, a role that may use smart
tools, and a squad whose profile allows the primitives it is built from. When
any of them is missing the page says which, rather than offering a box that
fails.

### Admin

The administrative console. Documented in
[administration.md](administration.md).

![The administrative console](images/ui-admin.png)

## How it is built

The interface is the engine project's own, adopted rather than rewritten —
see [ADR-0011](adr/0011-adopt-the-upstream-interface.md). React 19, Three.js
through @react-three/fiber, Tailwind 4, built with Vite.

```
gateway/webui/            the source, and what was changed (README.md there)
└── src/
    ├── api/              rpc.ts (/mcp), auth.ts (PKCE), session.ts,
    │                     platform.ts (the endpoints, as tool calls), admin.ts
    ├── components/       GraphTab, StatsTab, AdminTab, SignIn, SquadPicker …
    └── hooks/            useGraphData — fetches the layout
```

`npm run build` produces `dist/`, which the image copies to
`/usr/local/lib/repo-mcp-ui`; `REPO_MCP_UI_DIR` points the gateway at it. The
build output is not committed — reviewing minified output is not reviewing.

Nothing is fetched from a CDN at runtime, so an air-gapped installation works.
An air-gapped *build* needs an npm mirror as well as a Python one, which is a
real cost of this choice and is recorded as such in the ADR.

Files under the interface directory are served without authentication — the
sign-in screen cannot require having signed in, and nothing there reveals
anything about a codebase. The route resolves the requested path and refuses
anything that lands outside the directory.

## Regenerating the screenshots

`scripts/ui-screenshots.py` drives the running interface and writes
`docs/images/ui-*.png`. Playwright is not a dependency of this project —
adding a Node toolchain for pictures would be a poor trade — so install it
when you need to:

```bash
pip install playwright && playwright install chromium
scripts/dev.sh gateway
python3 scripts/ui-screenshots.py --project <an-indexed-project>
```

## What is not there yet

- **No writes to a codebase.** The interface reads. Triggering an index, or
  writing an ADR, is a tool call an MCP client can make and this cannot.
- **No graph history.** The map shows the graph as it is now. Comparing two
  points in time is [ADR-0004](adr/0004-graph-history.md) and unbuilt.
- **No saved views.** A filter selection and a camera position last as long as
  the page does.
