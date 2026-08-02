# ADR-0007: A local administrator exists alongside LDAP identity

- **Status:** Accepted
- **Context:** Configuration moved into the database
  ([ADR-0006](0006-configuration-in-the-database.md)), which raised the question
  of who may change it before the identity provider is configured.

## Context

Every user of the platform authenticates through OIDC, federated from LDAP,
and the gateway deliberately keeps no user table
([docs/architecture.md](../architecture.md)).

That leaves a hole at the beginning. The OIDC issuer, the audience and the
group claim are themselves configuration. On a fresh deployment nobody can
authenticate, because nothing has told the platform where to authenticate
against — and nobody can fix it, because fixing it requires authenticating.

The same hole reopens whenever the identity provider is unreachable, which is
exactly when an operator most needs to look at the configuration.

## Decision

A small number of **local administrator accounts** live in the database,
separate from LDAP identity. They exist for one purpose: administering the
platform, including the identity settings themselves.

- The first one is created at bootstrap, interactively or from
  `ADMIN_USERNAME` / `ADMIN_PASSWORD`. If no password is supplied one is
  generated and printed once.
- Passwords are hashed with Argon2id. A minimum length of 12 characters and 5
  distinct characters is enforced; there is no character-class maze.
- Authentication verifies against a real dummy hash when the account does not
  exist, so a missing user and a wrong password take the same time.
- These accounts reach the **administrative API only**. They cannot call MCP
  tools, cannot read a graph and cannot read source. Squad membership and
  capabilities remain LDAP-driven and are not expressible for a local account.
- Both services refuse to serve until at least one active administrator
  exists.

## Rationale

**The bootstrap hole is real and cannot be closed by configuration.** Some
credential has to exist before the identity provider does. The honest options
are a local account or a static token in the environment; an account is
auditable, rotatable and revocable, and a static token is none of those.

**Scope is what makes it safe.** The dangerous version of this idea is an
account that can do everything a user can. This one cannot query a graph or
read a snippet, so a compromised local administrator can misconfigure the
platform — which is loud, audited and reversible — but cannot quietly read
another squad's source, which is the outcome the whole tenancy model exists to
prevent.

**Refusing to start without one** turns a confusing failure into a clear
message. A gateway with no administrator and no identity configuration answers
every request with an authentication error that names none of that.

## Consequences

**Positive**

- A fresh deployment reaches a usable state without editing files on a host.
- The identity provider can be configured, and repaired, through the platform.
- Administrative actions are attributable: every change records an actor.
- Losing access to LDAP does not lock an operator out of the configuration.

**Negative, accepted**

- A password-based credential now exists in a system that otherwise has none.
  It is a standing target, and its blast radius is the whole configuration.
  Mitigated by scope, hashing, auditing, and by expecting it to be used rarely.
- The generated bootstrap password is printed once to a terminal or a
  container log. An operator who loses it has to reset it from the CLI, and a
  log aggregator will have captured it — documented in
  [docs/deployment.md](../deployment.md).
- Two authentication paths mean two things to keep correct. The administrative
  API and the MCP surface share no code beyond the audit record, deliberately.
- Nothing here removes the need for the identity provider. It is a way in
  before and around it, not a replacement.

## Alternatives considered

**A static admin token in the environment.** Rejected. It is one shared
secret, attributable to nobody, rotated by a restart, and it tends to live
forever in a Compose file. An account is strictly better on every one of
those.

**Bootstrap by designating an LDAP group as administrators, via an environment
variable.** Rejected as the only mechanism: it assumes LDAP is already
reachable and correctly mapped, which is precisely what cannot be assumed on
first boot or during an outage. It is a good *second* path and remains
available — the `admin` role is granted by group like any other.

**Seed configuration from files at first start and have no administrator at
all.** Rejected: it puts us back where ADR-0006 started, needing host access
for an ordinary administrative act, and leaves no way to change anything at
runtime.

**Let local administrators use the MCP surface too, "since they are admins".**
Rejected. It would make one password the way to read every squad's source, and
it would put a non-LDAP identity into an authorization model whose entire
premise is directory group membership.
