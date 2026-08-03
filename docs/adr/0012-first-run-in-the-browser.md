# ADR-0012: Create the first administrator in the browser

- **Status:** Accepted
- **Context:** A fresh install had no administrator until one was created server-side, from a password printed to a container log.

## Context

The platform cannot be configured without an administrator: squads, connectors,
secrets and the identity provider are all entered through the admin API, and the
gateway reports "not ready" until an administrator exists
([ADR-0007](0007-break-glass-administrator.md)). That administrator was created
by the `init` container running `repo-mcp-admin init`, which — when
`ADMIN_PASSWORD` was empty — generated a password and printed it once to its log.

So the first thing a new operator did, on every kind of install, was
`docker compose logs init` (or the Kubernetes equivalent) to read a generated
password out of a log. For someone trying the platform locally, or running it at
home, that is a poor first five minutes, and it is the step most easily missed.

## Decision

Create the first administrator in the browser, on first open.

- The `init` container creates the administrator only when `ADMIN_PASSWORD` is
  set, or when the command is run interactively. Otherwise it leaves the
  database without one and says so.
- While there is no administrator, the gateway serves a `/setup` page and two
  endpoints — `GET /api/bootstrap` and `POST /api/bootstrap/admin` — the only
  ones that answer before the platform is configured. Opening `/ui` redirects to
  `/setup`.
- `POST /api/bootstrap/admin` creates the administrator **only while there is
  none**. The moment one exists it returns 409 and `/setup` redirects to `/ui`.
  It is a one-time door, closed by the thing it creates.
- Creating the administrator refreshes readiness, so the platform is usable
  without a restart.

## Rationale

The primitive was already there and already safe: `ensure_admin` creates the
first administrator and returns "already exists" for every call after, so it
never resets a password. Exposing it over one guarded endpoint moves account
creation to where the operator already is — the browser — without a second code
path for it.

Deferring rather than removing the server-side creation keeps the automated and
enterprise paths intact: set `ADMIN_PASSWORD` from a secret, in CI or Helm, and
the account is created without a browser, exactly as before. Which path a
deployment takes is decided by whether that variable is set, not by a different
install procedure.

## Consequences

**Positive**

- A fresh install is a browser away: open the interface, create the
  administrator, carry on. No log to grep.
- One flow serves both ends — a laptop trial and an enterprise deployment —
  selected by whether `ADMIN_PASSWORD` is set, not by a separate install path.
- The endpoint is testable without a database: the gate and the administrator
  store are injected, so the denial path is an ordinary unit test.

**Negative, accepted**

- There is a window, between first boot and the first administrator being
  created, in which whoever reaches `/setup` first becomes the administrator. On
  a machine only its operator can reach — a laptop, a home server, a cluster
  behind an ingress not yet public — that is acceptable, and it is the same
  window the printed-password approach had: a log reader could use that password
  too. An operator who cannot accept the window sets `ADMIN_PASSWORD`, and there
  is none: the account exists before the gateway serves anything.
- The gateway now answers three routes before it is configured. They are inert
  once an administrator exists and reveal nothing about a codebase, but they are
  a slightly larger unauthenticated surface than "health probes only".

## Alternatives considered

- **Keep printing the password to the log as the default.** Rejected: it is the
  step new operators miss, and it reads as a secret left lying in a log. Kept as
  the `ADMIN_PASSWORD` path, for automation and for deployments that must be
  secured before they first serve.
- **Guard the first-run endpoint with a one-time token printed at boot.** Secure
  even on an exposed instance, but it puts the operator back to copying a value
  out of a log — the thing this set out to remove. The `ADMIN_PASSWORD` path
  already covers "must be secure before first serve", so a token would add a
  third mode for no new capability.
- **Allow first-run only outside production (`ENVIRONMENT != production`).**
  Rejected as too clever: the install path should not change with an environment
  label, and a home and an enterprise operator both want the same simple first
  open. Security-sensitive deployments use `ADMIN_PASSWORD` regardless of the
  label.
