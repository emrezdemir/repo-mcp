"""Bootstrap environment.

Only what must be known *before* the database can be read. Everything else an
administrator changes lives in the database — see
docs/adr/0006-configuration-in-the-database.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class EnvError(RuntimeError):
    """A required bootstrap variable is missing or malformed."""


@dataclass(frozen=True)
class DatabaseEnv:
    url: str
    pool_size: int
    pool_max_overflow: int
    #: How often a service re-checks the configuration generation counter.
    config_poll_seconds: float
    #: Seconds to keep retrying at startup. A bundled database usually needs a
    #: few seconds after the service container starts.
    connect_retry_seconds: float

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    def redacted_url(self) -> str:
        """The URL with any password removed, for logs and health output."""
        if "@" not in self.url:
            return self.url
        scheme, _, rest = self.url.partition("://")
        credentials, _, host = rest.rpartition("@")
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"


def database_env() -> DatabaseEnv:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise EnvError(
            "DATABASE_URL is not set. repo-mcp keeps its configuration in "
            "PostgreSQL; point this at the bundled database "
            "(postgresql+asyncpg://repomcp:...@postgres:5432/repomcp) or at "
            "your own instance."
        )
    # A plain postgresql:// URL selects the synchronous driver and fails at
    # connect time with a confusing error, so correct it here.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    return DatabaseEnv(
        url=url,
        pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
        pool_max_overflow=int(os.getenv("DATABASE_POOL_MAX_OVERFLOW", "5")),
        config_poll_seconds=float(os.getenv("CONFIG_POLL_SECONDS", "15")),
        connect_retry_seconds=float(os.getenv("DATABASE_CONNECT_RETRY_SECONDS", "60")),
    )


def secrets_key() -> str:
    """The Fernet key protecting credentials at rest.

    Refuses to fall back to a default. A generated-per-boot key would silently
    make every stored credential unreadable after a restart, which looks like
    data loss rather than a configuration mistake.
    """
    key = os.getenv("SECRETS_KEY", "").strip()
    if not key:
        raise EnvError(
            "SECRETS_KEY is not set. Provider tokens are encrypted at rest with "
            "it, so it must be stable across restarts and identical on every "
            "replica. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"'
        )
    return key
