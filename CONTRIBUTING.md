# Contributing

Thanks for taking the time. This project is early, so the most valuable
contributions are the ones that sharpen the design as much as the ones that
add code.

## Getting set up

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

cd gateway && pip install -e '.[dev]' && pytest && cd ..
cd indexer && pip install -e '.[dev]' && pytest && cd ..
```

The tests need neither the engine binary nor network access. Anything that does
belongs behind a marker, not in the default run.

For an end-to-end environment, see [docs/deployment.md](docs/deployment.md).

## Before you open a pull request

- `pytest` passes in both `gateway/` and `indexer/`.
- `ruff check .` and `ruff format --check .` are clean.
- New behaviour has a test. Authorization changes need one for the denial
  path, not only the allow path.
- Documentation is updated in the same change. A feature that is not in
  `docs/` does not exist for whoever comes next.

## Things worth knowing before you change things

**The engine is not ours to modify.** repo-mcp wraps a third-party indexing
engine (see [NOTICE](NOTICE)) and never patches it — see [ADR-0001](docs/adr/0001-wrap-dont-fork.md). If
something needs an engine change, it is an upstream issue, and we work around
it here in the meantime.

**Authorization is three independent layers.** Gateway ACL, engine tool
profile, filesystem roots
([docs/roles-and-permissions.md](docs/roles-and-permissions.md)). A change
that makes one layer depend on another is a change to the security model —
please raise it as an issue first.

**Claims about engine behaviour need a source reference.**
[docs/engine.md](docs/engine.md) cites files in the engine's tree
rather than its documentation, deliberately, so reviewers can verify rather
than trust. Keep that standard.

**Be honest in the roadmap.** [docs/roadmap.md](docs/roadmap.md) separates
built from designed. Moving something into *Done* means it works and is
tested.

## Architecture decisions

Anything that changes the tenancy model, the authorization model, the engine
boundary or the data flow deserves an ADR in `docs/adr/`. Copy the shape of an
existing one: context, decision, rationale, consequences (including the
negative ones), and alternatives considered.

Open an issue to discuss the decision before writing a large implementation.
It is cheaper to disagree about an ADR than about a merged pull request.

## Reporting bugs

Include the version, what you ran, what happened, and what you expected. For
anything involving authorization or data exposure, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## Style

- Python 3.11+, `ruff` for linting and formatting, 100-column lines.
- Comments explain *why*, not *what*. If a constraint from the engine or a
  provider forced the shape of the code, say so — that is exactly the comment
  the next reader needs.
- Error messages are read by operators at 3am. Say what was wrong and what was
  expected.

## Licence

Contributions are accepted under the MIT licence of this project.
