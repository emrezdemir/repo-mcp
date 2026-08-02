"""Ask a connector whether it actually works, and say so in words.

Configuring a connector is four things that must all be right at once — the
provider, the container name, a token with the right scope, and patterns that
keep something — and until this existed none of them was confirmed at the time
of typing. A wrong organisation name and an expired token both produced the
same symptom hours later: nothing was indexed, with no indication of which of
the four was wrong.

So this does the only thing that settles it: it runs real discovery against
the provider and reports what came back. It is read-only — enumerating
repositories, never cloning or writing — and it is bounded, because a check
that hangs is not a check.

The result is written for whoever is looking at the form. A provider's own
error is an HTTP status code, and "401" is not an instruction; "the token was
refused — it is invalid, expired, or lacks the scope to list this
organisation" is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import httpx

from .providers import build_provider, selected

#: Enough to prove discovery works and to show the patterns doing something,
#: without enumerating an organisation of several thousand for a check.
SAMPLE_LIMIT = 200

#: Names carried back for display. The count is the useful number; the names
#: are there so a wrong organisation with a valid token is obvious at a glance.
SHOWN = 10

#: A check is something a person waits for, so it fails sooner than the
#: indexer would.
TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class CheckResult:
    """What a connector can see, or why it cannot see anything."""

    ok: bool
    #: Empty when ok; otherwise one sentence naming what to change.
    reason: str = ""
    #: Repositories the provider returned, up to `SAMPLE_LIMIT`.
    discovered: int = 0
    #: Of those, the ones this connector's patterns would index.
    matched: int = 0
    #: Discovered but not indexable — archived or empty.
    skipped: int = 0
    #: `SAMPLE_LIMIT` was reached, so the counts are a floor rather than a total.
    truncated: bool = False
    #: First few matched names, for display.
    sample: tuple[str, ...] = ()
    #: First few names the patterns excluded, so a pattern that quietly keeps
    #: nothing is visible rather than inferred from a zero.
    excluded: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "discovered": self.discovered,
            "matched": self.matched,
            "skipped": self.skipped,
            "truncated": self.truncated,
            "sample": list(self.sample),
            "excluded": list(self.excluded),
        }


async def check_connector(
    *,
    provider: str,
    settings: Mapping[str, object],
    token: str | None,
    include: Iterable[str] = ("*",),
    exclude: Iterable[str] = (),
    limit: int = SAMPLE_LIMIT,
    timeout: float = TIMEOUT_SECONDS,
) -> CheckResult:
    """Run discovery once and describe the outcome.

    Never raises for a configuration or provider fault: those are the answer,
    not an error, and the caller is a form waiting for a sentence.
    """
    include = tuple(include) or ("*",)
    exclude = tuple(exclude)

    if not token:
        return CheckResult(
            ok=False,
            reason=(
                "no access token: choose a stored secret for this connector, "
                "or add one first"
            ),
        )

    try:
        built = build_provider({"type": provider, **dict(settings)}, token)
    except KeyError as exc:
        missing = str(exc).strip("'")
        return CheckResult(ok=False, reason=f"{provider} needs the {missing!r} setting")
    except ValueError as exc:
        return CheckResult(ok=False, reason=str(exc))

    discovered = matched = skipped = 0
    sample: list[str] = []
    excluded: list[str] = []
    truncated = False

    try:
        async with asyncio.timeout(timeout):
            async for repo in built.discover():
                discovered += 1
                if not repo.is_indexable():
                    skipped += 1
                elif selected(repo.full_name, include, exclude):
                    matched += 1
                    if len(sample) < SHOWN:
                        sample.append(repo.full_name)
                elif len(excluded) < SHOWN:
                    excluded.append(repo.full_name)
                if discovered >= limit:
                    truncated = True
                    break
    except TimeoutError:
        return CheckResult(
            ok=False,
            reason=(
                f"the provider did not answer within {timeout:.0f} seconds; "
                "check the base URL and whether this host can reach it"
            ),
        )
    except httpx.HTTPStatusError as exc:
        return CheckResult(ok=False, reason=_explain_status(exc, provider))
    except httpx.HTTPError as exc:
        return CheckResult(ok=False, reason=f"could not reach the provider: {exc}")

    if discovered == 0:
        return CheckResult(
            ok=False,
            reason=(
                "the provider answered but holds no repositories — the name is "
                "probably right and empty, or the token cannot see them"
            ),
        )

    if matched == 0:
        return CheckResult(
            ok=False,
            reason=(
                f"{discovered} repositories found and the patterns keep none of "
                f"them; include={', '.join(include)}"
                + (f" exclude={', '.join(exclude)}" if exclude else "")
            ),
            discovered=discovered,
            skipped=skipped,
            truncated=truncated,
            excluded=tuple(excluded),
        )

    return CheckResult(
        ok=True,
        discovered=discovered,
        matched=matched,
        skipped=skipped,
        truncated=truncated,
        sample=tuple(sample),
        excluded=tuple(excluded),
    )


#: What each provider calls the thing a connector points at, so a 404 names
#: the field the administrator actually typed into.
_CONTAINER = {"github": "organisation", "gitlab": "group", "bitbucket": "workspace"}


def _explain_status(exc: httpx.HTTPStatusError, provider: str) -> str:
    status = exc.response.status_code
    container = _CONTAINER.get(provider, "container")
    if status in (401, 403):
        return (
            "the token was refused — it is invalid, expired, or lacks the "
            f"scope to list this {container}"
        )
    if status == 404:
        return f"no such {container}, or the token cannot see it"
    if status == 429:
        return "the provider is rate-limiting this token; try again shortly"
    if status >= 500:
        return f"the provider returned {status}; this is on their side, not the configuration"
    return f"the provider refused the request with {status}"
