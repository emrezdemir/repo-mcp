"""Webhook signature verification and payload normalisation.

Each provider signs and shapes its push events differently. Normalising them
into a single ``PushEvent`` keeps the routing logic provider-agnostic.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


class WebhookError(Exception):
    """The webhook could not be verified or understood."""


@dataclass(frozen=True)
class PushEvent:
    full_name: str
    sha: str
    ref: str
    provider: str


def verify_github(body: bytes, signature: str | None, secret: str) -> None:
    if not signature:
        raise WebhookError("missing X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookError("signature mismatch")


def verify_gitlab(token: str | None, secret: str) -> None:
    # GitLab sends a shared secret rather than a signature; compare in
    # constant time anyway so the check does not leak length information.
    if not token or not hmac.compare_digest(token, secret):
        raise WebhookError("invalid X-Gitlab-Token")


def verify_bitbucket(body: bytes, signature: str | None, secret: str) -> None:
    if not signature:
        raise WebhookError("missing X-Hub-Signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookError("signature mismatch")


def parse_github(payload: dict) -> PushEvent:
    try:
        return PushEvent(
            full_name=payload["repository"]["full_name"],
            sha=payload.get("after", ""),
            ref=payload.get("ref", ""),
            provider="github",
        )
    except (KeyError, TypeError) as exc:
        raise WebhookError(f"unexpected GitHub payload: {exc}") from exc


def parse_gitlab(payload: dict) -> PushEvent:
    try:
        return PushEvent(
            full_name=payload["project"]["path_with_namespace"],
            sha=payload.get("after", ""),
            ref=payload.get("ref", ""),
            provider="gitlab",
        )
    except (KeyError, TypeError) as exc:
        raise WebhookError(f"unexpected GitLab payload: {exc}") from exc


def parse_bitbucket(payload: dict) -> PushEvent:
    try:
        changes = payload["push"]["changes"]
        if not changes:
            raise WebhookError("push event carried no changes")
        new = changes[0].get("new") or {}
        return PushEvent(
            full_name=payload["repository"]["full_name"],
            sha=(new.get("target") or {}).get("hash", ""),
            ref=new.get("name", ""),
            provider="bitbucket",
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise WebhookError(f"unexpected Bitbucket payload: {exc}") from exc


#: A deleted branch reports the all-zero SHA; there is nothing to index.
NULL_SHA = "0" * 40


def is_deletion(event: PushEvent) -> bool:
    return not event.sha or event.sha == NULL_SHA
