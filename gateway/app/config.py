"""Gateway configuration, sourced entirely from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- identity ---
    oidc_issuer: str
    oidc_audience: str
    oidc_groups_claim: str
    #: Skips JWT verification and accepts a static token. Intended for local
    #: development only; the app logs a warning at startup when enabled.
    dev_insecure_auth: bool
    dev_static_token: str
    dev_static_groups: tuple[str, ...]

    # --- indexing engine ---
    cbm_binary: str
    cbm_cache_root: Path
    cbm_repo_root: Path
    cbm_idle_timeout_s: float
    cbm_call_timeout_s: float

    # --- LLM (LiteLLM proxy) ---
    litellm_base_url: str
    litellm_api_key: str
    litellm_model: str
    litellm_timeout_s: float
    smart_tools_enabled: bool

    @classmethod
    def from_env(cls) -> Settings:
        groups = os.getenv("DEV_STATIC_GROUPS", "")
        return cls(
            oidc_issuer=os.getenv("OIDC_ISSUER", ""),
            oidc_audience=os.getenv("OIDC_AUDIENCE", "repo-mcp"),
            oidc_groups_claim=os.getenv("OIDC_GROUPS_CLAIM", "groups"),
            dev_insecure_auth=_bool("DEV_INSECURE_AUTH", False),
            dev_static_token=os.getenv("DEV_STATIC_TOKEN", ""),
            dev_static_groups=tuple(g.strip() for g in groups.split(",") if g.strip()),
            cbm_binary=os.getenv("CBM_BINARY", "codebase-memory-mcp"),
            cbm_cache_root=Path(os.getenv("CBM_CACHE_ROOT", "/var/lib/repo-mcp/cache")),
            cbm_repo_root=Path(os.getenv("CBM_REPO_ROOT", "/var/lib/repo-mcp/repos")),
            cbm_idle_timeout_s=float(os.getenv("CBM_IDLE_TIMEOUT_S", "900")),
            cbm_call_timeout_s=float(os.getenv("CBM_CALL_TIMEOUT_S", "120")),
            litellm_base_url=os.getenv("LITELLM_BASE_URL", ""),
            litellm_api_key=os.getenv("LITELLM_API_KEY", ""),
            litellm_model=os.getenv("LITELLM_MODEL", "gpt-4o-mini"),
            litellm_timeout_s=float(os.getenv("LITELLM_TIMEOUT_S", "90")),
            smart_tools_enabled=_bool("SMART_TOOLS_ENABLED", True),
        )
