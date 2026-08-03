"""Report the running version, and — unless told not to — whether a newer one
exists.

The interface reads `GET /api/version` to show the version it is running and,
when the check is on, a banner once a newer release is published on GitHub. The
check is a single call to the public releases API, cached for six hours, and
turned off with `UPDATE_CHECK=false` — an air-gapped install should not phone
home, and nothing about the deployment is sent either way.

`scripts/upgrade.sh` is the other half: this notices, that applies.
"""

from __future__ import annotations

import logging
import os
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

log = logging.getLogger(__name__)

REPO = "emrezdemir/repo-mcp"
_CACHE_TTL_S = 6 * 3600
_cache: dict[str, float | str | None] = {"checked_at": 0.0, "latest": None}


def current_version() -> str:
    """The running gateway's version, from its installed package metadata."""
    try:
        return package_version("repo-mcp-gateway")
    except PackageNotFoundError:
        return "unknown"


def _is_newer(current: str, candidate: str) -> bool:
    """True if `candidate` is a newer version than `current`.

    Compared as integer tuples, not strings, so 0.3.10 is newer than 0.3.2.
    """

    def parts(v: str) -> list[int]:
        return [int(p) for p in v.strip().lstrip("v").split(".") if p.isdigit()]

    try:
        return parts(candidate) > parts(current)
    except ValueError:
        return False


def _check_disabled() -> bool:
    return os.getenv("UPDATE_CHECK", "true").strip().lower() in {"0", "false", "no", "off"}


async def latest_release() -> str | None:
    """The latest published release tag, or None if the check is off, offline,
    rate-limited, or nothing is published yet. Cached, so the interface asking on
    every load costs one call every six hours."""
    if _check_disabled():
        return None

    now = time.monotonic()
    if now - float(_cache["checked_at"] or 0) < _CACHE_TTL_S:
        return _cache["latest"]  # type: ignore[return-value]

    latest: str | None = None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
        if response.status_code == 200:
            tag = str(response.json().get("tag_name", "")).lstrip("v")
            latest = tag or None
    except Exception as exc:  # noqa: BLE001 — a failed check is not an error here
        log.debug("update check failed: %s", exc)

    _cache["checked_at"] = now
    _cache["latest"] = latest
    return latest


async def version_info() -> dict:
    """What `GET /api/version` returns: the running version, the latest known,
    and whether an upgrade is available."""
    current = current_version()
    latest = await latest_release()
    return {
        "version": current,
        "latest": latest,
        "update_available": bool(latest and _is_newer(current, latest)),
    }
