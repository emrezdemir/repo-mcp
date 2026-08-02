"""Scan configuration: connectors, tenant routing and per-repo bindings."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .providers import DiscoveredRepo, Provider, build_provider

VALID_MODES = {"full", "moderate", "fast", "cross-repo-intelligence"}

#: The engine validates project names; keep to a conservative, path-safe subset.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ConfigError(ValueError):
    """scan.yaml is malformed."""


def project_name(full_name: str) -> str:
    """Derive a stable engine project name from a provider-qualified repo name.

    ``acme/backend/payments-api`` becomes ``acme-backend-payments-api``. It has
    to stay stable across runs: changing it orphans the existing graph.
    """
    return _UNSAFE.sub("-", full_name).strip("-")


@dataclass(frozen=True)
class Connector:
    name: str
    kind: str
    tenant: str
    raw: dict
    #: Environment variable holding the token. Used when the connector came
    #: from YAML; database-backed connectors carry the value in `token`.
    secret_env: str = ""
    #: Token resolved from the configuration database.
    token: str | None = None
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    mode: str = "moderate"
    persistence: bool = True
    #: Cron expression for the periodic full rescan of this connector.
    schedule_cron: str | None = None

    def matches(self, repo: DiscoveredRepo) -> bool:
        if not repo.is_indexable():
            return False
        short = repo.full_name.split("/")[-1]
        included = any(
            fnmatch.fnmatchcase(repo.full_name, p) or fnmatch.fnmatchcase(short, p)
            for p in self.include
        )
        if not included:
            return False
        return not any(
            fnmatch.fnmatchcase(repo.full_name, p) or fnmatch.fnmatchcase(short, p)
            for p in self.exclude
        )

    def build(self) -> Provider:
        # A token stored in the configuration database wins; the environment
        # variable remains supported so an existing YAML setup keeps working.
        secret = self.token or (os.getenv(self.secret_env, "") if self.secret_env else "")
        if not secret:
            where = f"${self.secret_env}" if self.secret_env else "the configuration database"
            raise ConfigError(
                f"connector {self.name!r} has no access token; set it in {where}"
            )
        return build_provider({"type": self.kind, **self.raw}, secret)


@dataclass(frozen=True)
class Binding:
    """A discovered repository bound to a tenant and a local working copy."""

    full_name: str
    project: str
    tenant: str
    clone_url: str
    default_branch: str
    workdir: Path
    mode: str
    persistence: bool


@dataclass(frozen=True)
class ScanConfig:
    connectors: tuple[Connector, ...]
    repo_root: Path

    @classmethod
    def load(cls, path: Path, repo_root: Path) -> ScanConfig:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError as exc:  # pragma: no cover - operational failure
            raise ConfigError(f"cannot read scan config {path}: {exc}") from exc
        return cls.from_dict(raw, repo_root)

    @classmethod
    def from_dict(
        cls, raw: dict, repo_root: Path, secrets: dict[str, str] | None = None
    ) -> ScanConfig:
        """Build from an already-parsed document.

        The configuration database produces the same shape the YAML file had,
        so both sources go through one code path. `secrets` maps a secret name
        to its plaintext, resolved by the caller.
        """
        secrets = secrets or {}
        entries = raw.get("connectors")
        if not isinstance(entries, list) or not entries:
            raise ConfigError("scan.yaml must define at least one connector")

        connectors: list[Connector] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ConfigError("each connector entry must be a mapping")
            for key in ("name", "type", "tenant"):
                if not entry.get(key):
                    raise ConfigError(f"connector is missing {key!r}: {entry}")
            if not entry.get("token_env") and not entry.get("token_secret"):
                raise ConfigError(
                    f"connector {entry['name']!r} needs token_env or token_secret"
                )
            name = str(entry["name"])
            if name in seen:
                raise ConfigError(f"duplicate connector name: {name!r}")
            seen.add(name)

            mode = str(entry.get("mode", "moderate"))
            if mode not in VALID_MODES:
                raise ConfigError(
                    f"connector {name!r}: unknown mode {mode!r} "
                    f"(expected one of {', '.join(sorted(VALID_MODES))})"
                )

            reserved = {"name", "type", "tenant", "token_env", "token_secret",
                        "include", "exclude", "mode", "persistence", "schedule_cron"}
            connectors.append(
                Connector(
                    name=name,
                    kind=str(entry["type"]).lower(),
                    tenant=str(entry["tenant"]),
                    raw={k: v for k, v in entry.items() if k not in reserved},
                    secret_env=str(entry.get("token_env", "")),
                    token=secrets.get(str(entry.get("token_secret", ""))) or None,
                    include=tuple(str(p) for p in entry.get("include", ["*"])),
                    exclude=tuple(str(p) for p in entry.get("exclude", [])),
                    mode=mode,
                    persistence=bool(entry.get("persistence", True)),
                    schedule_cron=(
                        str(entry["schedule_cron"]) if entry.get("schedule_cron") else None
                    ),
                )
            )
        return cls(tuple(connectors), repo_root)

    def bind(self, connector: Connector, repo: DiscoveredRepo) -> Binding:
        project = project_name(repo.full_name)
        return Binding(
            full_name=repo.full_name,
            project=project,
            tenant=connector.tenant,
            clone_url=repo.clone_url,
            default_branch=repo.default_branch,
            workdir=self.repo_root / connector.tenant / project,
            mode=connector.mode,
            persistence=connector.persistence,
        )
