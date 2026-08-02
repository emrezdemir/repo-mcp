# Memory bank

Durable project context for agents and for anyone returning to this repository
after a gap. An agent starts every session with no memory of the last one;
these files are that memory.

## The files

Ordered from most stable to most volatile. Read them in this order — each one
assumes the ones above it.

| File | Answers | Changes |
| --- | --- | --- |
| [projectbrief.md](projectbrief.md) | What are we building, for whom, and what is out of scope? | Rarely. A change here is a change of direction. |
| [productContext.md](productContext.md) | Why does this exist? Who uses it and how? | Rarely. |
| [systemPatterns.md](systemPatterns.md) | How is it built, and which invariants must hold? | When architecture changes — with an ADR. |
| [techContext.md](techContext.md) | Stack, dependencies, constraints, environment. | When dependencies or the toolchain change. |
| [activeContext.md](activeContext.md) | What is in flight right now? What did the last session decide? | **Every session.** |
| [progress.md](progress.md) | What works, what does not, what is known broken? | **Every session that changes behaviour.** |

## The protocol

**At the start of a session:** read `activeContext.md` and `progress.md`
first. If they contradict the code, the code is right — fix the file as part
of your work and say so.

**At the end of a session:** update `activeContext.md` (what you did, what you
decided, what is next) and `progress.md` (what moved between "works" and "does
not"). This is part of the definition of done in
[AGENTS.md §9](../AGENTS.md), not an optional courtesy.

**When architecture changes:** update `systemPatterns.md` *and* write an ADR
in [`docs/adr/`](../docs/adr/). The memory bank records the current shape; an
ADR records why it changed and what was rejected. Both are needed — one
without the other loses either the state or the reasoning.

## What belongs here, and what does not

This is **project state and context**, not documentation.

| Belongs here | Belongs in `docs/` |
| --- | --- |
| What is in flight this week | How to deploy the thing |
| Which invariants must not break | The full role and permission reference |
| What we tried that did not work | The architecture explanation |
| Known-broken things and their workarounds | Engine constraints with source references |

If a paragraph would still be true and useful in a year, it probably belongs
in `docs/`. If it describes the current moment, it belongs here.

## Honesty rule

These files are read by someone acting on them without the context you have
right now. An optimistic `progress.md` causes real wasted work: an agent
builds on top of something described as working, discovers it is not, and
throws away the result.

Write what is true. "Designed, not implemented" is a perfectly good status.
