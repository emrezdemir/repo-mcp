"""Repository discovery across GitHub, GitLab and Bitbucket.

You point the platform at an organisation, group or project and it enumerates
the repositories underneath, so onboarding a squad does not mean listing
several hundred repository URLs by hand.

The three providers model "a container of repositories" differently:

* **GitHub** — an organisation owns repositories directly.
* **GitLab** — a group owns projects and can nest subgroups arbitrarily, so
  discovery must recurse (``include_subgroups=true``).
* **Bitbucket Cloud** — a workspace owns repositories, and an optional project
  key partitions them.

Each provider returns the same :class:`DiscoveredRepo` shape so the rest of
the indexer stays provider-agnostic.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

_PAGE_SIZE = 100
#: Guards against a misconfigured scope enumerating an entire SaaS tenant.
_MAX_PAGES = 200


@dataclass(frozen=True)
class DiscoveredRepo:
    #: Provider-qualified identifier, e.g. "acme/payments-api".
    full_name: str
    clone_url: str
    default_branch: str
    archived: bool = False
    empty: bool = False

    def is_indexable(self) -> bool:
        return not self.archived and not self.empty


class Provider(Protocol):
    name: str

    def discover(self) -> AsyncIterator[DiscoveredRepo]:
        ...


class GitHubProvider:
    """Enumerates repositories in a GitHub organisation.

    Works against github.com and GitHub Enterprise Server by changing
    ``base_url`` (``https://ghe.example.com/api/v3``).
    """

    name = "github"

    def __init__(self, *, org: str, token: str, base_url: str = "https://api.github.com") -> None:
        self._org = org
        self._token = token
        self._base_url = base_url.rstrip("/")

    async def discover(self) -> AsyncIterator[DiscoveredRepo]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=30.0) as c:
            for page in range(1, _MAX_PAGES + 1):
                response = await c.get(
                    f"/orgs/{self._org}/repos",
                    params={"per_page": _PAGE_SIZE, "page": page, "type": "all"},
                )
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    return
                for repo in batch:
                    yield DiscoveredRepo(
                        full_name=repo["full_name"],
                        clone_url=repo["clone_url"],
                        default_branch=repo.get("default_branch") or "main",
                        archived=bool(repo.get("archived")),
                        empty=bool(repo.get("size", 1) == 0),
                    )
                if len(batch) < _PAGE_SIZE:
                    return
            log.warning("github: stopped after %d pages for org=%s", _MAX_PAGES, self._org)


class GitLabProvider:
    """Enumerates projects in a GitLab group, including nested subgroups."""

    name = "gitlab"

    def __init__(
        self, *, group: str, token: str, base_url: str = "https://gitlab.com"
    ) -> None:
        self._group = group
        self._token = token
        self._base_url = base_url.rstrip("/")

    async def discover(self) -> AsyncIterator[DiscoveredRepo]:
        headers = {"PRIVATE-TOKEN": self._token}
        # A group path such as "acme/backend" has to be URL-encoded into a
        # single path segment for the API.
        group_id = httpx.URL(self._group).path.strip("/").replace("/", "%2F")
        async with httpx.AsyncClient(
            base_url=f"{self._base_url}/api/v4", headers=headers, timeout=30.0
        ) as c:
            for page in range(1, _MAX_PAGES + 1):
                response = await c.get(
                    f"/groups/{group_id}/projects",
                    params={
                        "per_page": _PAGE_SIZE,
                        "page": page,
                        "include_subgroups": "true",
                        "archived": "false",
                    },
                )
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    return
                for project in batch:
                    yield DiscoveredRepo(
                        full_name=project["path_with_namespace"],
                        clone_url=project["http_url_to_repo"],
                        default_branch=project.get("default_branch") or "main",
                        archived=bool(project.get("archived")),
                        empty=project.get("default_branch") is None,
                    )
                if len(batch) < _PAGE_SIZE:
                    return
            log.warning("gitlab: stopped after %d pages for group=%s", _MAX_PAGES, self._group)


class BitbucketProvider:
    """Enumerates repositories in a Bitbucket Cloud workspace.

    When ``project_key`` is given, only that project's repositories are
    returned; otherwise the whole workspace is enumerated.
    """

    name = "bitbucket"

    def __init__(
        self,
        *,
        workspace: str,
        username: str,
        app_password: str,
        project_key: str | None = None,
        base_url: str = "https://api.bitbucket.org/2.0",
    ) -> None:
        self._workspace = workspace
        self._auth = (username, app_password)
        self._project_key = project_key
        self._base_url = base_url.rstrip("/")

    async def discover(self) -> AsyncIterator[DiscoveredRepo]:
        params: dict[str, str | int] = {"pagelen": _PAGE_SIZE}
        if self._project_key:
            params["q"] = f'project.key="{self._project_key}"'

        url: str | None = f"/repositories/{self._workspace}"
        async with httpx.AsyncClient(
            base_url=self._base_url, auth=self._auth, timeout=30.0
        ) as c:
            pages = 0
            while url and pages < _MAX_PAGES:
                # Bitbucket returns absolute follow-up URLs in `next`; the
                # query string is already baked in, so params go on page 1 only.
                response = await c.get(url, params=params if pages == 0 else None)
                response.raise_for_status()
                payload = response.json()
                for repo in payload.get("values", []):
                    clone = next(
                        (
                            link["href"]
                            for link in repo.get("links", {}).get("clone", [])
                            if link.get("name") == "https"
                        ),
                        None,
                    )
                    if not clone:
                        log.warning("bitbucket: no https clone url for %s", repo.get("full_name"))
                        continue
                    yield DiscoveredRepo(
                        full_name=repo["full_name"],
                        clone_url=clone,
                        default_branch=(repo.get("mainbranch") or {}).get("name") or "main",
                        empty=repo.get("mainbranch") is None,
                    )
                url = payload.get("next")
                pages += 1
            if url:
                log.warning(
                    "bitbucket: stopped after %d pages for workspace=%s",
                    _MAX_PAGES,
                    self._workspace,
                )


def build_provider(config: dict, secret: str, secret2: str = "") -> Provider:
    """Construct a provider from a ``connectors:`` entry in scan config."""
    kind = str(config.get("type", "")).lower()
    if kind == "github":
        return GitHubProvider(
            org=str(config["org"]),
            token=secret,
            base_url=str(config.get("base_url", "https://api.github.com")),
        )
    if kind == "gitlab":
        return GitLabProvider(
            group=str(config["group"]),
            token=secret,
            base_url=str(config.get("base_url", "https://gitlab.com")),
        )
    if kind == "bitbucket":
        return BitbucketProvider(
            workspace=str(config["workspace"]),
            username=str(config["username"]),
            app_password=secret,
            project_key=config.get("project_key"),
            base_url=str(config.get("base_url", "https://api.bitbucket.org/2.0")),
        )
    raise ValueError(f"unknown connector type: {kind!r}")
