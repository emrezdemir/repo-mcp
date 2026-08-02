# AGENTS.md

Working agreement for coding agents and humans in this repository. Agents read
this file first; the rules here are binding, not advisory.

Tool-specific notes live in [CLAUDE.md](CLAUDE.md). Longer-lived project
context lives in [memory-bank/](memory-bank/). Where they disagree, this file
wins.

---

## 1. What this project is

repo-mcp is a self-hosted service that turns a company's repositories into a
shared, queryable knowledge graph, exposed over MCP with LDAP-backed identity
and squad-level isolation.

Two Python services around a third-party indexing engine:

| Path | What it is |
| --- | --- |
| `gateway/` | MCP over HTTP: authentication, authorization, audit, the engine bridge, LLM-backed composite tools |
| `indexer/` | Repository discovery, webhooks, scheduled and CI-triggered indexing |
| `deploy/` | Dockerfile, Compose stack, Helm chart, example configuration |
| `scripts/` | Setup, test, dev, debug, smoke, e2e, secret scanning |
| `docs/` | Architecture, engine constraints, roles, deployment, scaling, ADRs |
| `memory-bank/` | Durable project context for agents |

Read [memory-bank/projectbrief.md](memory-bank/projectbrief.md) before
changing anything architectural.

## 2. Start here, every session

```bash
make setup       # once: virtualenvs, config, pre-commit hook
make test        # must be green before you start and before you finish
```

Then read, in this order:

1. `memory-bank/activeContext.md` — what is in flight right now
2. `memory-bank/progress.md` — what works and what does not
3. The doc for the area you are touching (see the table in §1)

## 3. Commands

Every one of these is a script in `scripts/`. Use them rather than
reinventing the invocation.

| Command | Purpose |
| --- | --- |
| `make setup` | Virtualenvs, dependencies, config from examples, generated secrets, pre-commit hook |
| `make test` | Lint and unit tests for both services, plus example-config validation |
| `make lint` / `make fmt` | Lint only / apply autofixes |
| `make dev` | Both services locally, auto-reload, no Docker, JWT verification off |
| `make debug` | Diagnose a broken setup; reports every finding, not just the first |
| `make up` / `make down` / `make logs` | Docker stack lifecycle |
| `make smoke` | Assertions against a running stack |
| `make e2e` | Build images, index a real repository, query it, tear down |
| `make check-docs` | Enforce the documentation rules mechanically |
| `make check-secrets` | Audit every tracked file for secrets |
| `make verify` | Tests, documentation rules and secret scan — the definition of done |
| `make helm-lint` | Lint the Helm chart |

Never invent a workflow that one of these already covers. If a workflow is
missing, add a script and a `make` target rather than documenting a command
someone has to copy by hand.

## 4. Git workflow

- Branch from **`dev`**. Open pull requests against **`dev`**.
- **`main` only moves when `dev` is merged into it.** Never push to `main`.
- Rebase or merge `dev` into your branch before opening a pull request.

```bash
git checkout dev && git pull origin dev
git checkout -b feature/short-description
```

Commit messages: imperative subject under ~72 characters, then a body that
explains **why**. The diff already shows what changed.

```
Add per-project locking to the index queue

Two workers picking up the same project block on the engine's mutation
lock, which wastes a worker slot for the length of an index run.
```

Do not add tool, model or assistant attribution to commits, pull requests,
code comments or any other artefact in this repository.

## 5. Hard rules

These are not style preferences. Breaking one is a bug.

**Never commit secrets or environment-specific configuration.**
`deploy/.env`, `deploy/tenants.yaml` and `deploy/scan.yaml` are ignored on
purpose; the `.example` files beside them are the tracked reference. A
pre-commit hook and a CI job both enforce this. See
[docs/branching.md](docs/branching.md).

**Never modify the indexing engine or vendor its source.** It is used as a
binary through its CLI and stdio interfaces only. See
[ADR-0001](docs/adr/0001-wrap-dont-fork.md).

**Never weaken the three authorization layers.** Role capabilities and project
allowlists in the gateway, the engine's own tool profile, and per-tenant
filesystem roots are independent by design. A change that makes one depend on
another changes the security model — raise an issue first. See
[docs/roles-and-permissions.md](docs/roles-and-permissions.md).

**Never expose the engine directly.** It has no authentication. The gateway is
the only ingress.

**Never claim engine behaviour without a source reference.**
[docs/engine.md](docs/engine.md) cites the engine's own source for every
claim so reviewers can verify rather than trust. Keep that standard.

**Never mark something done in the roadmap unless it works and is tested.**
[docs/roadmap.md](docs/roadmap.md) separates built from designed, and people
make decisions based on that split.

## 6. Code standards

Full detail in [docs/code-standards.md](docs/code-standards.md). The short
version:

Every mechanically checkable rule is enforced by `make verify`; the rest is
what review is for.

- Python 3.11+, `ruff` for lint and format, 100-column lines.
- Type hints on public functions. `from __future__ import annotations` at the
  top of every module.
- Comments explain **why**, never what. When an engine or provider constraint
  forced the shape of the code, say so — that is the comment the next reader
  needs.
- Error messages are read by an operator at 3am: name what was wrong and what
  was expected, including the value or path involved.
- Configuration comes from the environment. No hardcoded hosts, paths,
  credentials or model names.
- Fail closed. An unknown role, tool or profile is denied, not allowed.

## 7. Testing

Four layers, separated by what they need:

| Layer | Command | Needs | Covers |
| --- | --- | --- | --- |
| Unit | `make test` | nothing | authorization, config parsing, discovery, queue behaviour, the stdio bridge against a fake engine |
| Config | `make test` | nothing | the shipped example files still parse |
| Smoke | `make smoke` | a running stack | handshake, auth rejections, live queries, metrics |
| End to end | `make e2e` | Docker | container images, the real engine, git cloning, a real repository indexed and queried |

Rules:

- Unit tests must not need the network or the engine binary. That is what
  keeps them fast enough to run on every save.
- **Authorization changes need a test for the denial path**, not only the
  allow path. A test that only proves access works proves nothing about
  access control.
- A test name states the behaviour: `test_developer_cannot_trigger_indexing`,
  not `test_roles_2`.
- Run `make e2e` if you touched the Dockerfile, the stdio bridge or the
  indexing path — unit tests deliberately do not cover those.

## 8. Documentation

Documentation ships in the same change as the code. A feature that is not in
`docs/` does not exist for whoever comes next.

- Prose is English. `README.tr.md` is the only translated file.
- Architectural decisions get an ADR in `docs/adr/`: context, decision,
  rationale, consequences **including the negative ones**, and alternatives
  considered. Copy the shape of an existing one.
- An ADR is required when a change touches the tenancy model, the
  authorization model, the engine boundary, or the data flow.
- Update `memory-bank/activeContext.md` and `memory-bank/progress.md` when
  you finish a piece of work. See [memory-bank/README.md](memory-bank/README.md).

## 9. Definition of done

A change is done when all of these hold:

- [ ] `make verify` is green (tests, documentation rules, secret scan)
- [ ] New behaviour has a test, including the denial path where relevant
- [ ] Documentation updated in the same commit
- [ ] An ADR added or updated, if §8 requires one
- [ ] `memory-bank/activeContext.md` and `progress.md` reflect reality
- [ ] The branch targets `dev`

Report honestly. If tests fail, say so and show the output. If you skipped
part of the scope, say which part and why. "Done" means verified, not
"probably fine".

## 10. When you are unsure

- **The answer is in the codebase** → read it. Do not guess at behaviour that
  can be checked in a minute.
- **A decision has a conventional default** → take it, state it, move on.
- **Two readings lead to materially different work** → ask.
- **A change would break a hard rule in §5** → stop and raise it, even if it
  was requested. Explain the constraint and offer the nearest safe thing.
