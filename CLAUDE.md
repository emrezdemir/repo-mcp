# CLAUDE.md

Claude Code specific notes. **[AGENTS.md](AGENTS.md) is the contract** —
commands, git workflow, hard rules, code standards, testing and the definition
of done all live there, and this file does not repeat them. Keeping one source
of truth is the point; two copies drift and then neither is trusted.

## Session start

```bash
make setup     # first time only
make test      # confirm green before changing anything
```

Read [memory-bank/activeContext.md](memory-bank/activeContext.md) and
[memory-bank/progress.md](memory-bank/progress.md). They are short and they
are where the last session left its state.

## Navigating this codebase

It is small — about 3,400 lines of Python across two services — so read the
real file rather than guessing. Fast orientation:

| Question | File |
| --- | --- |
| How is a request authorized? | `gateway/app/mcp.py` (`_authorize`, `Session.effective_tools`) |
| What can a role do? | `gateway/app/roles.py` |
| How is a squad isolated? | `gateway/app/tenants.py`, `gateway/app/cbm.py` (`_env`) |
| How does the engine bridge work? | `gateway/app/cbm.py` |
| How are repositories discovered? | `common/repo_mcp_common/providers.py` |
| How does indexing get triggered? | `indexer/app/main.py`, `indexer/app/worker.py` |
| Why is the design like this? | `docs/adr/`, `docs/engine.md` |

Grep before you spawn a search agent — on a repository this size, a targeted
`grep` usually beats a subagent round trip.

## Working here

**Prefer the scripts.** `make debug` exists precisely so you do not have to
hand-assemble a diagnosis; it checks the toolchain, engine, configuration,
storage, both services, a live MCP round trip and the model backend, and
reports everything it finds. It has already caught two real bugs.

**Verify with a run, not a claim.** The services start without Docker
(`make dev`) and the endpoints answer immediately. If you changed behaviour
that a curl can demonstrate, demonstrate it.

**The engine binary is usually absent locally.** Everything except tool
execution works without it, and a tool call returns a clear
`engine binary not found` error. Do not treat that as a bug in your change.

**Long output belongs in a file, not the transcript.** Write to the scratchpad
and report the conclusion.

## Editing rules that bite here

- `deploy/tenants.yaml` and `deploy/scan.yaml` are **generated from the
  `.example` files and ignored by git**. Edit the `.example` file when you
  mean to change the shipped default; edit the local file when you mean to
  change your own setup. Committing the local one is blocked by a hook.
- Anything under `gateway/.venv/` or `indexer/.venv/` is not source.
- **The site renders `docs/`.** `site/*.html` is the landing page, in Turkish
  and English; every page under `/docs/` on the site is generated from the
  markdown by `scripts/render-docs.py`. Edit the markdown, not the output. A
  new document must be added to that script's `ORDER`, or the build fails —
  publishing a page nothing links to is the same as not publishing it.
  `.site-venv/` holds Python-Markdown and is not source.
- `CBM_*` environment variable names, the engine binary name and
  `gateway/app/cbm.py` keep the engine's own naming — that is a real contract.
  Prose elsewhere says "the engine".

## Before you say you are finished

Run `make verify` — tests, documentation rules and the secret scan in one
gate — then the checklist in [AGENTS.md §9](AGENTS.md). Then update
`memory-bank/activeContext.md` and `memory-bank/progress.md` — the next
session starts from those two files, and stale ones are worse than none.

## Reporting

State what you verified and how. If `make test` failed, show the output rather
than describing it. If part of the scope was skipped, name the part and the
reason. Do not add tool or model attribution to anything that lands in the
repository.
