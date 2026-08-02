# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Use GitHub's [private vulnerability reporting][gh] on this repository, or
email the maintainers listed in `CODEOWNERS`. You should get an
acknowledgement within a few working days.

Helpful to include: affected version or commit, a description of the impact, and
the smallest reproduction you can manage.

[gh]: https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability

## What we consider in scope

This project handles source code and identity, so the interesting classes are:

- **Cross-tenant access.** Any path where one squad reaches another squad's
  graph or source. All three authorization layers are in scope
  ([docs/roles-and-permissions.md](docs/roles-and-permissions.md)).
- **Authentication bypass.** Token verification, JWKS handling, the
  `X-Tenant` selection path, the CI trigger token.
- **Webhook forgery.** Signature verification for GitHub, GitLab and
  Bitbucket.
- **Privilege escalation via roles.** A capability reachable by a role that
  should not have it, including through the LLM-backed composite tools.
- **Path traversal into the engine.** Anything that escapes
  `CBM_ALLOWED_ROOT` or a tenant's cache directory.
- **Secret disclosure.** Tokens or keys appearing in logs, audit records, or
  error messages returned to clients.

## Deployment expectations

Some properties are the operator's responsibility, and a report that depends
on breaking them is a configuration issue rather than a vulnerability:

- **The engine is never exposed directly.** The indexing engine has no
  authentication of its own. The gateway must be the only ingress.
- **`DEV_INSECURE_AUTH` is off in production.** It skips JWT verification and
  exists for local development; the gateway logs a warning when it is enabled.
- **Provider tokens are read-only** where discovery is all that is needed.
- **Prompt logging is a deliberate choice.** Prompts sent to LiteLLM can
  contain source code. Decide whether they are retained, and where.

## Upstream

repo-mcp embeds a third-party indexing engine (see [NOTICE](NOTICE)).
Vulnerabilities in the engine itself belong in that project's own security
process. If an engine issue is exploitable specifically because of how
repo-mcp deploys it, report it here as well — that part is ours.
