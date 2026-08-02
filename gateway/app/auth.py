"""OIDC / JWT verification.

Identity lives in LDAP or Active Directory. Keycloak federates it and issues
OIDC tokens; LDAP group membership arrives as a claim. The gateway therefore
keeps no user table of its own — revoking an LDAP group revokes access at the
next token refresh.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from jose import jwt
from jose.exceptions import JWTError

from .config import Settings


class AuthError(Exception):
    """Authentication failed; surfaces as HTTP 401."""


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    groups: frozenset[str]

    @property
    def is_service_account(self) -> bool:
        return self.username.startswith("service-account-")


class _JwksCache:
    """Fetches and caches the issuer's signing keys via OIDC discovery."""

    def __init__(self, issuer: str, ttl_s: float = 3600.0) -> None:
        self._issuer = issuer.rstrip("/")
        self._ttl = ttl_s
        self._keys: dict | None = None
        self._fetched_at = 0.0

    async def keys(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._keys is not None and now - self._fetched_at < self._ttl:
            return self._keys
        async with httpx.AsyncClient(timeout=10.0) as client:
            meta = await client.get(f"{self._issuer}/.well-known/openid-configuration")
            meta.raise_for_status()
            jwks = await client.get(meta.json()["jwks_uri"])
            jwks.raise_for_status()
        self._keys = jwks.json()
        self._fetched_at = now
        return self._keys


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks = _JwksCache(settings.oidc_issuer) if settings.oidc_issuer else None

    async def authenticate(self, authorization: str | None) -> Principal:
        token = _bearer(authorization)

        if self._settings.dev_insecure_auth:
            return self._dev_principal(token)

        if self._jwks is None:
            raise AuthError("OIDC_ISSUER is not configured")

        claims = await self._verify(token)
        groups = claims.get(self._settings.oidc_groups_claim) or []
        if isinstance(groups, str):
            groups = [groups]
        return Principal(
            subject=str(claims.get("sub", "")),
            username=str(claims.get("preferred_username") or claims.get("sub") or ""),
            # Keycloak renders groups as "/squad-payments"; the leading slash
            # would never match the plain names used in tenants.yaml.
            groups=frozenset(str(g).lstrip("/") for g in groups),
        )

    async def _verify(self, token: str) -> dict:
        assert self._jwks is not None
        for force in (False, True):
            # After key rotation the cache is stale. Retry once with a forced
            # refresh when the failure looks like an unknown key id.
            keys = await self._jwks.keys(force=force)
            try:
                return jwt.decode(
                    token,
                    keys,
                    audience=self._settings.oidc_audience,
                    issuer=self._settings.oidc_issuer.rstrip("/"),
                    options={"verify_at_hash": False},
                )
            except JWTError as exc:
                if force or "kid" not in str(exc).lower():
                    raise AuthError(f"token verification failed: {exc}") from exc
        raise AuthError("token verification failed")

    def _dev_principal(self, token: str) -> Principal:
        expected = self._settings.dev_static_token
        if not expected or token != expected:
            raise AuthError("invalid static token")
        return Principal(
            subject="dev",
            username="dev",
            groups=frozenset(self._settings.dev_static_groups),
        )


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header must be 'Bearer <token>'")
    return token.strip()
