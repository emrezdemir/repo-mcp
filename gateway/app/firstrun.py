"""First-run setup, in the browser.

A fresh install has a schema but no administrator, and until one exists the
platform cannot be configured. It used to be created server-side — by the
`init` container, which printed a generated password to its log — so the first
thing a new operator did was grep a container log. This lets them do it in the
browser instead: open the interface, create the administrator, carry on.

The endpoints here are the only ones that answer before the platform is
configured, and they answer *only* while there is no administrator. The moment
one exists, `create_admin` reports it and `/setup` sends the browser on to the
interface — so this is a one-time door, not a standing one. An operator who
would rather create the account without a browser sets `ADMIN_PASSWORD` and the
`init` container does it as before; see docs/adr/0012-first-run-in-the-browser.md.

Nothing here needs a codebase or a squad, so none of it is gated on `ready()`.
It holds no state of its own: whether setup is still needed, how to create the
administrator, and how to refresh readiness afterwards are all passed in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .audit import AuditEvent, emit

#: needs_setup() -> whether the platform still has no administrator.
#: create_admin(username, password) -> True if created, False if one already
#: exists; raises ValueError with a readable message for a weak password.
#: refresh() -> re-read readiness so the platform is usable without a restart.
NeedsSetup = Callable[[], bool]
CreateAdmin = Callable[[str, str], Awaitable[bool]]
Refresh = Callable[[], Awaitable[None]]


def build_router(needs_setup: NeedsSetup, create_admin: CreateAdmin, refresh: Refresh) -> APIRouter:
    router = APIRouter(tags=["setup"])

    @router.get("/api/bootstrap", include_in_schema=False)
    async def bootstrap_status() -> JSONResponse:
        """Whether the interface should show first-run setup. Public by design."""
        return JSONResponse({"needs_setup": needs_setup()})

    @router.post("/api/bootstrap/admin", include_in_schema=False)
    async def create_first_admin(request: Request) -> JSONResponse:
        """Create the first administrator, once and only while there is none."""
        if not needs_setup():
            return JSONResponse({"error": "an administrator already exists"}, status_code=409)

        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)

        username = str(body.get("username") or "admin").strip()
        password = str(body.get("password") or "")
        if not password:
            return JSONResponse({"error": "a password is required"}, status_code=400)

        try:
            created = await create_admin(username, password)
        except ValueError as exc:
            # A weak password or a bad username — the message names what to fix.
            return JSONResponse({"error": str(exc)}, status_code=400)

        if not created:
            # A racing request created one between the guard above and here.
            return JSONResponse({"error": "an administrator already exists"}, status_code=409)

        await refresh()
        emit(AuditEvent(event="admin/bootstrap", principal=username, outcome="ok"))
        return JSONResponse({"ok": True, "username": username})

    @router.get("/setup", include_in_schema=False)
    async def setup_page() -> HTMLResponse | RedirectResponse:
        """The first-run page, or a redirect to the interface once set up."""
        if not needs_setup():
            return RedirectResponse("/ui", status_code=303)
        return HTMLResponse(SETUP_HTML)

    return router


#: Served inline: no build step, no CDN, so an air-gapped install works. The
#: palette is the interface's own so the two look like one thing.
SETUP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up repo-mcp</title>
<style>
  :root {
    --bg:#0a161a; --panel:#0b1c22; --raised:#0f2229; --fg:#e0eded;
    --muted:#6a9e9e; --border:#1a3a40; --primary:#1da27e; --danger:#e2555a;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; min-height:100vh; display:grid; place-items:center;
    background:radial-gradient(1000px 500px at 80% -10%,#103038 0%,transparent 60%),var(--bg);
    color:var(--fg); font:15px/1.6 var(--sans); -webkit-font-smoothing:antialiased;
  }
  .card {
    width:min(440px,92vw); background:linear-gradient(180deg,var(--raised),var(--panel));
    border:1px solid var(--border); border-radius:14px; padding:30px 28px;
    box-shadow:0 24px 60px rgba(0,0,0,.5);
  }
  .brand { display:flex; align-items:center; gap:9px; font-weight:650; margin-bottom:4px; }
  .dot {
    width:8px; height:8px; border-radius:50%;
    background:var(--primary); box-shadow:0 0 12px var(--primary);
  }
  h1 { font-size:20px; letter-spacing:-.02em; margin:14px 0 6px; }
  p.lede { color:var(--muted); font-size:13.5px; margin:0 0 20px; }
  label { display:block; font-size:12px; color:var(--muted); margin:14px 0 6px; }
  input {
    width:100%; padding:10px 12px; border-radius:9px; border:1px solid var(--border);
    background:#071216; color:var(--fg); font:14px var(--sans);
  }
  input:focus { outline:none; border-color:var(--primary); }
  button {
    width:100%; margin-top:22px; padding:11px; border:none; border-radius:9px;
    background:var(--primary); color:#04120f; font-weight:600; font-size:14px; cursor:pointer;
  }
  button:disabled { opacity:.6; cursor:default; }
  .msg { margin-top:14px; font-size:13px; min-height:1.2em; }
  .msg.err { color:var(--danger); }
  .done { text-align:left; }
  .done ol { color:var(--muted); font-size:13.5px; padding-left:18px; margin:12px 0 20px; }
  .done li { margin-bottom:6px; }
  a.button { display:block; text-align:center; text-decoration:none; }
  code {
    font-family:var(--mono); font-size:12.5px; background:#071216;
    border:1px solid var(--border); border-radius:5px; padding:1px 6px;
  }
</style>
</head>
<body>
<div class="card">
  <div class="brand"><span class="dot"></span> repo-mcp</div>
  <div id="form-view">
    <h1>Create your administrator</h1>
    <p class="lede">This first account configures the platform — squads,
      connectors, secrets and the identity provider. It is created once, here.</p>
    <form id="f">
      <label for="u">Username</label>
      <input id="u" name="username" value="admin" autocomplete="username" autofocus>
      <label for="p">Password</label>
      <input id="p" name="password" type="password" autocomplete="new-password">
      <label for="p2">Repeat password</label>
      <input id="p2" type="password" autocomplete="new-password">
      <button id="go" type="submit">Create administrator</button>
      <div class="msg" id="msg"></div>
    </form>
  </div>
  <div id="done-view" class="done" hidden>
    <h1>Administrator created</h1>
    <p class="lede">Sign in with it, then continue:</p>
    <ol>
      <li>Add a <b>connector</b> — a provider, an organisation and a read-only token.</li>
      <li>Add a <b>squad</b> and map it to your identity groups.</li>
      <li>Point the platform at your <b>OIDC</b> provider for everyone else.</li>
    </ol>
    <a class="button" href="/ui">Open the interface</a>
  </div>
</div>
<script>
  const f = document.getElementById('f'), msg = document.getElementById('msg'),
        go = document.getElementById('go');
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    msg.className = 'msg'; msg.textContent = '';
    const username = document.getElementById('u').value.trim();
    const password = document.getElementById('p').value;
    if (password !== document.getElementById('p2').value) {
      msg.className = 'msg err'; msg.textContent = 'Passwords do not match.'; return;
    }
    go.disabled = true;
    try {
      const r = await fetch('/api/bootstrap/admin', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password}),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        document.getElementById('form-view').hidden = true;
        document.getElementById('done-view').hidden = false;
        return;
      }
      msg.className = 'msg err';
      msg.textContent = data.error || 'Could not create the administrator.';
    } catch (err) {
      msg.className = 'msg err'; msg.textContent = 'Network error — is the gateway up?';
    }
    go.disabled = false;
  });
</script>
</body>
</html>
"""
