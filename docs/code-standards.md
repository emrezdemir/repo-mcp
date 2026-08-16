# Code and documentation standards

Binding rules. Where a rule can be checked mechanically it is, by `make test`,
`make check-docs`, `make check-secrets` or CI — a rule nobody enforces is a
suggestion, and suggestions rot.

Each rule below is marked **[enforced]** or **[reviewed]**. Reviewed rules are
what code review is for.

---

## 1. Python

### Formatting and lint — [enforced]

`ruff` decides. 100-column lines, `E F W I UP B SIM` rule sets, target
`py311`. `make fmt` fixes what it can; `make lint` must be clean.

### Module preamble — [reviewed]

```python
"""One line saying what this module is.

Then the non-obvious part: a constraint it works around, an invariant it
maintains, or why it exists at all. Skip this paragraph if there isn't one.
"""

from __future__ import annotations
```

`from __future__ import annotations` goes in every module, so annotations stay
cheap and forward references work.

### Types — [reviewed]

- Public functions and dataclass fields are annotated. Locals only where the
  type is not obvious.
- Modern syntax: `str | None`, `list[str]`, `frozenset[str]`.
- Immutable data is `@dataclass(frozen=True)`. Configuration objects are built
  once at startup and never mutated.

### Naming — [reviewed]

- `snake_case` functions, `PascalCase` classes, `UPPER_SNAKE` constants.
- A leading underscore means private to the module.
- Names say what the thing is, not what type it has: `allowed_tools`, not
  `tool_set`.
- Booleans read as assertions: `structural_only`, `is_error`, `dev_insecure_auth`.

### Comments — [reviewed]

Comments explain **why**. The code already shows what.

```python
# Bad — restates the code
# Set the cache directory for this tenant
env["CBM_CACHE_DIR"] = self.cache_dir

# Good — explains the constraint
# The cache directory is the isolation unit: list_projects returns
# everything in it, so squads cannot share one.
env["CBM_CACHE_DIR"] = self.cache_dir
```

When an engine, provider or protocol constraint forced the shape of the code,
say so. That is the comment the next reader actually needs.

Use `#:` for attribute documentation that belongs with a constant.

### Errors — [reviewed]

- Raise a domain exception (`CbmError`, `AccessDenied`, `ConfigError`), never
  a bare `Exception`.
- The message names what was wrong **and** what was expected, with the value:

  ```python
  raise AccessDenied(
      f"no access to project {project!r} "
      f"(allowed: {', '.join(session.tenant.projects)})"
  )
  ```

- `raise ... from exc` when wrapping. Losing the cause loses the debugging.
- Never swallow an exception silently. If it is genuinely ignorable, use
  `contextlib.suppress` and say why in a comment.
- Configuration errors fail at startup, not on the first request.

### Fail closed — [reviewed]

Unknown role, unknown tool, unknown profile, missing token, malformed config:
deny or refuse to start. Never default to permissive. Do not distinguish
"unknown tool" from "not permitted" in a message to a caller — the difference
is itself information.

### Async — [reviewed]

- Subprocess and network work is `async`. Never block the event loop.
- Every `await` on something external has a timeout.
- A timeout that leaves a stream ambiguous tears the connection down rather
  than retrying on it.
- Background tasks catch `asyncio.CancelledError` and re-raise; they never die
  from an ordinary exception.

### Configuration — [enforced by review and `check-secrets`]

- Every value comes from the environment or an ignored file. No hardcoded
  hosts, paths, credentials, model names or organisation names.
- Secrets are referenced by environment variable **name** in config files,
  never by value.
- New variables are added to `deploy/.env.example` in the same change.

## 2. Tests

### Required — [enforced]

- New behaviour has a test.
- **Authorization changes have a test for the denial path.** A test that only
  proves access works proves nothing about access control.
- Unit tests need no network and no engine binary.

### Naming — [reviewed]

A test name is a sentence about behaviour:

```
test_developer_cannot_trigger_indexing        good
test_burst_for_one_project_is_coalesced       good
test_roles_2                                  useless
```

### Shape — [reviewed]

- One behaviour per test.
- Fixtures for setup, not for assertions.
- When a test encodes a non-obvious invariant, a one-line docstring says which:

  ```python
  async def test_timeout_tears_down_the_process():
      """A late reply must not be mistaken for the next call's result."""
  ```

## 3. Shell scripts

- `#!/usr/bin/env bash` and `set -euo pipefail` (via `scripts/lib.sh`).
- A usage comment at the top; `--help` prints it.
- ShellCheck clean at `warning` severity — [enforced]
- `bash -n` clean — [enforced]
- Executable bit set, except `lib.sh` — [enforced]
- Diagnostic scripts report **every** finding, not just the first.
- A script that overwrites user files stashes and restores them.
- **Target bash 3.2, not just the bash on this machine.** macOS ships 3.2 and
  is a supported development host; Linux servers ship 5.x. The difference that
  actually bites is empty arrays: under `set -u`, bash 3.2 treats
  `"${arr[@]}"` and `"${arr[*]}"` on an empty array as a fatal *unbound
  variable*, where bash 4.4 and newer expand to nothing. `${#arr[@]}` is safe.
  Write `${arr[@]+"${arr[@]}"}` when passing a possibly-empty array to a
  command, or guard the whole statement with `[[ ${#arr[@]} -gt 0 ]] &&`.
  Neither CI nor an Ubuntu server will ever catch a mistake here — three
  commands (`make test`, `make up`, `make setup`) shipped broken on macOS for
  exactly this reason.
- **A `make` target that is not a file must be `.PHONY`.** `site` was not, a
  `site/` directory exists, and `make site` therefore answered "up to date" and
  built nothing — on every platform, for as long as the target existed.
- **The `Makefile` targets GNU Make 3.81.** That is what macOS ships, from
  2006; Linux is on 4.3 or newer. Both are GNU Make and the current file works
  on either — verified by running the same targets on both — but nothing added
  in 4.x is available: no `.ONESHELL`, no `$(file ...)`, no `!=` shell
  assignment, no `.RECIPEPREFIX`, no `undefine`, no `private`. `.DEFAULT_GOAL`
  is the newest thing in use and it arrived exactly in 3.81. The same trap as
  the bash rule above: CI and a Linux server will never catch it, and the
  failure is silent rather than loud.

## 4. Commits

- Imperative subject, ~72 characters, no trailing period.
- A body explaining **why**. The diff shows what.
- One logical change per commit.
- No tool, model or assistant attribution anywhere — commits, pull requests,
  code comments, or any other artefact. — [reviewed, and take it seriously]

## 5. Documentation

### Rules — [enforced where marked]

1. **Documentation ships in the same change as the code.** A feature not in
   `docs/` does not exist for whoever comes next.
2. **Every internal link resolves.** — [enforced by `make check-docs`]
3. **Every command in `AGENTS.md` exists as a `make` target.** — [enforced]
4. **Every memory-bank file exists and is non-empty.** — [enforced]
5. **`CHANGELOG.md` has an `## [Unreleased]` section.** — [enforced]
6. **Every ADR has the required sections.** — [enforced]
7. **Every doc in the README index exists.** — [enforced]
8. Prose is English, with one exception: `README.md` is Turkish and
   `README.en.md` carries the English. Both are updated together — a
   change to one that skips the other is an incomplete change. Everything
   under `docs/` stays English.
9. **Both READMEs are written plainly.** Short sentences, ordinary words, no
   literary register. In the Turkish one, keep the English terms developers
   actually say — gateway, indexer, repo, webhook, graph, connector, token,
   commit — instead of translating them into words nobody uses. No
   circumflexes (`â`, `î`, `û`). A README is the first thing a stranger reads;
   it should not read like a specification.
9. Claims about engine behaviour cite the engine's source. Documentation is
   not evidence; source is.
10. Status language is exact. "Works" means run and verified. Anything else
    says what it actually is — see `memory-bank/progress.md`.

### ADRs — [enforced]

Required whenever a change touches the tenancy model, the authorization
model, the engine boundary, or the data flow.

`docs/adr/NNNN-short-title.md`, with these sections:

```markdown
# ADR-NNNN: Title in the imperative

- **Status:** Proposed | Accepted | Superseded by ADR-NNNN
- **Context:** one line

## Context
## Decision
## Rationale
## Consequences
### Positive / Negative, accepted
## Alternatives considered
```

**Consequences must include the negative ones**, and **alternatives must say
why they were rejected**. An ADR that only lists upsides is marketing, and it
is useless to the person who later wonders whether the obvious alternative was
considered.

### Writing style — [reviewed]

- Say the thing. "The chart refuses to render" beats "it is not recommended
  to".
- Tables for facts, prose for reasoning.
- Show the failure mode, not just the rule: *"Not NFS — WAL locking is
  unreliable there and corrupts stores silently."*
- No marketing adjectives. No "simply", "just", "obviously".

## 6. Definition of done

Repeated from [AGENTS.md §9](../AGENTS.md) because it is the rule people skip:

- [ ] `make test` green
- [ ] `make check-docs` green
- [ ] `make check-secrets` clean
- [ ] Test for new behaviour, including the denial path where relevant
- [ ] Documentation updated in the same commit
- [ ] ADR added or updated if §5 requires one
- [ ] `memory-bank/activeContext.md` and `progress.md` reflect reality
- [ ] Branch targets `dev`

Report honestly. Failing tests get shown, not summarised. Skipped scope gets
named. "Done" means verified.
