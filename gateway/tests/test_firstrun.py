"""Tests for first-run setup: the browser creates the first administrator, once.

The router holds no state and takes no database — whether setup is still needed,
how to create the administrator, and how to refresh readiness are all injected —
so these exercise the gate itself: it works exactly once, and never after an
administrator exists.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.firstrun import build_router


def make_app(needs_setup: bool):
    """An app whose first-run router is backed by a togglable flag and a fake
    administrator store, so the gate is tested without a database."""
    state = {"needs_setup": needs_setup, "created": []}

    def needs_setup_fn() -> bool:
        return state["needs_setup"]

    async def create_admin(username: str, password: str) -> bool:
        if len(password) < 8:
            raise ValueError("password is too short")
        if not state["needs_setup"]:
            return False
        state["created"].append(username)
        return True

    async def refresh() -> None:
        state["needs_setup"] = not state["created"]

    app = FastAPI()
    app.include_router(build_router(needs_setup_fn, create_admin, refresh))
    return app, state


def test_bootstrap_reports_setup_is_needed_before_an_admin_exists():
    app, _ = make_app(needs_setup=True)
    assert TestClient(app).get("/api/bootstrap").json() == {"needs_setup": True}


def test_the_setup_page_is_served_while_setup_is_needed():
    r = TestClient(make_app(needs_setup=True)[0]).get("/setup")
    assert r.status_code == 200
    assert "Create your administrator" in r.text


def test_creating_the_first_admin_succeeds_and_closes_the_door():
    app, state = make_app(needs_setup=True)
    client = TestClient(app)
    r = client.post("/api/bootstrap/admin", json={"username": "ada", "password": "correcthorse"})
    assert r.status_code == 200
    assert r.json()["username"] == "ada"
    assert state["created"] == ["ada"]
    assert client.get("/api/bootstrap").json() == {"needs_setup": False}


def test_a_second_administrator_is_refused_once_one_exists():
    """The denial path: the bootstrap endpoint works once and never again."""
    client = TestClient(make_app(needs_setup=False)[0])
    r = client.post(
        "/api/bootstrap/admin", json={"username": "mallory", "password": "correcthorse"}
    )
    assert r.status_code == 409


def test_the_setup_page_redirects_to_the_interface_once_set_up():
    r = TestClient(make_app(needs_setup=False)[0]).get("/setup", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ui"


def test_a_weak_password_is_refused_with_a_reason():
    client = TestClient(make_app(needs_setup=True)[0])
    r = client.post("/api/bootstrap/admin", json={"username": "ada", "password": "short"})
    assert r.status_code == 400
    assert "short" in r.json()["error"].lower()


def test_a_missing_password_is_refused():
    client = TestClient(make_app(needs_setup=True)[0])
    r = client.post("/api/bootstrap/admin", json={"username": "ada"})
    assert r.status_code == 400
