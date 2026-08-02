from __future__ import annotations

import pytest

from app.providers import DiscoveredRepo
from app.repos import ConfigError, ScanConfig, project_name
from app.webhooks import (
    PushEvent,
    WebhookError,
    is_deletion,
    parse_bitbucket,
    parse_github,
    parse_gitlab,
    verify_github,
)


def config(tmp_path, **overrides):
    base = {
        "connectors": [
            {
                "name": "acme-gh",
                "type": "github",
                "org": "acme",
                "tenant": "payments",
                "token_env": "GH_TOKEN",
                "include": ["payments-*"],
                "exclude": ["*-legacy"],
            }
        ]
    }
    base.update(overrides)
    path = tmp_path / "scan.yaml"
    import yaml

    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return ScanConfig.load(path, tmp_path / "repos")


def repo(full_name: str, **kwargs) -> DiscoveredRepo:
    return DiscoveredRepo(
        full_name=full_name,
        clone_url=f"https://example.com/{full_name}.git",
        default_branch=kwargs.pop("default_branch", "main"),
        **kwargs,
    )


def test_project_name_is_path_safe_and_stable():
    assert project_name("acme/payments-api") == "acme-payments-api"
    assert project_name("acme/backend/payments api") == "acme-backend-payments-api"
    assert project_name("acme//weird__name") == "acme-weird__name"


def test_include_and_exclude_patterns(tmp_path):
    connector = config(tmp_path).connectors[0]
    assert connector.matches(repo("acme/payments-api"))
    assert not connector.matches(repo("acme/hr-portal"))
    assert not connector.matches(repo("acme/payments-legacy"))


def test_archived_and_empty_repos_are_skipped(tmp_path):
    connector = config(tmp_path).connectors[0]
    assert not connector.matches(repo("acme/payments-api", archived=True))
    assert not connector.matches(repo("acme/payments-api", empty=True))


def test_binding_places_workdir_under_tenant(tmp_path):
    scan = config(tmp_path)
    binding = scan.bind(scan.connectors[0], repo("acme/payments-api"))
    assert binding.tenant == "payments"
    assert binding.project == "acme-payments-api"
    assert binding.workdir == tmp_path / "repos" / "payments" / "acme-payments-api"


def test_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="unknown mode"):
        config(
            tmp_path,
            connectors=[
                {
                    "name": "x",
                    "type": "github",
                    "org": "a",
                    "tenant": "t",
                    "token_env": "E",
                    "mode": "turbo",
                }
            ],
        )


def test_duplicate_connector_names_are_rejected(tmp_path):
    entry = {"name": "dup", "type": "github", "org": "a", "tenant": "t", "token_env": "E"}
    with pytest.raises(ConfigError, match="duplicate connector"):
        config(tmp_path, connectors=[entry, dict(entry)])


def test_github_signature_verification():
    body = b'{"ok":true}'
    secret = "s3cret"
    import hashlib
    import hmac

    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    verify_github(body, good, secret)
    with pytest.raises(WebhookError):
        verify_github(body, "sha256=deadbeef", secret)
    with pytest.raises(WebhookError):
        verify_github(body, None, secret)


def test_push_event_parsing_per_provider():
    gh = parse_github(
        {"repository": {"full_name": "acme/api"}, "after": "a" * 40, "ref": "refs/heads/main"}
    )
    assert gh == PushEvent("acme/api", "a" * 40, "refs/heads/main", "github")

    gl = parse_gitlab(
        {
            "project": {"path_with_namespace": "acme/backend/api"},
            "after": "b" * 40,
            "ref": "refs/heads/main",
        }
    )
    assert gl.full_name == "acme/backend/api"
    assert gl.provider == "gitlab"

    bb = parse_bitbucket(
        {
            "repository": {"full_name": "acme/api"},
            "push": {"changes": [{"new": {"name": "main", "target": {"hash": "c" * 40}}}]},
        }
    )
    assert bb.sha == "c" * 40
    assert bb.ref == "main"


def test_branch_deletion_is_detected():
    assert is_deletion(PushEvent("acme/api", "0" * 40, "refs/heads/x", "github"))
    assert is_deletion(PushEvent("acme/api", "", "refs/heads/x", "github"))
    assert not is_deletion(PushEvent("acme/api", "a" * 40, "refs/heads/x", "github"))


def test_malformed_payloads_raise():
    with pytest.raises(WebhookError):
        parse_github({"nope": True})
    with pytest.raises(WebhookError):
        parse_bitbucket({"repository": {"full_name": "a/b"}, "push": {"changes": []}})
