"""Tests for version reporting and the update check."""

from __future__ import annotations

from app.updates import _is_newer, current_version, version_info


def test_newer_compares_as_numbers_not_strings():
    assert _is_newer("0.3.0", "0.3.1")
    assert _is_newer("0.3.2", "0.3.10")  # a string comparison would get this wrong
    assert _is_newer("0.9.9", "1.0.0")
    assert not _is_newer("0.4.0", "0.3.9")
    assert not _is_newer("0.3.0", "0.3.0")


def test_a_v_prefix_and_junk_do_not_break_the_comparison():
    assert _is_newer("v0.3.0", "v0.4.0")
    assert not _is_newer("0.3.0", "not-a-version")


async def test_version_info_reports_no_update_when_the_check_is_off(monkeypatch):
    """UPDATE_CHECK=false is the air-gapped setting: report the version, ask
    nothing of GitHub."""
    monkeypatch.setenv("UPDATE_CHECK", "false")
    info = await version_info()
    assert info["version"] == current_version()
    assert info["latest"] is None
    assert info["update_available"] is False
