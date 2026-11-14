"""Public mode: run AND reveal are admin-only, enforced at route level (lead decision on #44, 2026-11-13).

An early public reveal would mark the event revealed and silently disqualify later admin runs, so in
FAULTLINE_MODE=public both state-changing replay routes need `Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>`.
The gate is a route dependency, so it holds with or without PR #28's edge middleware. Local mode stays open.
Read-only pre-reveal routes (/api/cases, /evidence) stay public. SYNTHETIC fixtures; mocked model.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request
from test_routes_replay import CANARY, EVENT, make_world, run

TOKEN = "test-admin-token-not-a-real-secret-0123456789"  # not key-shaped; >= 32 chars
GATED = ("run", "reveal")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    return make_world(tmp_path, monkeypatch)


def _saved_prediction(world) -> str:
    """A prediction persisted while in local mode (the gate is checked afterwards)."""
    resp = run(world.client())
    assert resp.status_code == 200, resp.text
    return resp.json()["prediction"]["prediction_id"]


def _call(client, route: str, pid: str, headers: dict | None = None):
    if route == "run":
        return client.post("/api/replay/run", json={"case_id": EVENT, "variant": "agent_only"}, headers=headers or {})
    return client.post(f"/api/replay/{pid}/reveal", headers=headers or {})


def _assert_refused(resp, status: int) -> None:
    assert resp.status_code == status, resp.text
    assert resp.json() == {"code": "ADMIN_TOKEN_REQUIRED", "message": resp.json()["message"]}
    assert resp.json()["message"]
    assert CANARY not in resp.text and TOKEN not in resp.text


def test_local_mode_is_open(world, monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    pid = _saved_prediction(world)
    assert world.client().post(f"/api/replay/{pid}/reveal").status_code == 200


@pytest.mark.parametrize("route", GATED)
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        (None, 401),
        ({"Authorization": "Basic abc"}, 401),
        ({"Authorization": "Bearer "}, 401),
        ({"Authorization": "Bearer wrong-token-of-sufficient-length-000000"}, 403),
    ],
)
def test_public_mode_refuses_without_the_admin_token(world, monkeypatch, route, headers, status):
    pid = _saved_prediction(world)
    n_requests = len(world.fake.requests)
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    _assert_refused(_call(world.client(), route, pid, headers), status)
    # Refused before any work: no model call, no new prediction, no reveal logged.
    assert len(world.fake.requests) == n_requests
    assert len(world.records()) == 1
    from core.store import PredictionStore

    assert PredictionStore(world.db).first_reveal(EVENT) is None


@pytest.mark.parametrize("route", GATED)
@pytest.mark.parametrize("configured", ["", "short-token"])
def test_public_mode_without_a_strong_token_configured_refuses_everyone(world, monkeypatch, route, configured):
    pid = _saved_prediction(world)
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", configured)
    headers = {"Authorization": f"Bearer {configured}"} if configured else None
    if configured:
        # A set-but-short token in public mode stops the app at startup (config.ConfigError, PR #28): closed.
        from config import ConfigError

        with pytest.raises(ConfigError):
            world.client()
        _assert_route_gate_refuses({"authorization": f"Bearer {configured}"}, 403)
        return
    _assert_refused(_call(world.client(), route, pid, headers), 401)


def _assert_route_gate_refuses(headers: dict[str, str], status: int) -> None:
    """The route-level gate on its own (behind the edge gate in a real app) also refuses."""
    from errors import FaultlineError
    from routes.replay import require_admin_in_public_mode

    scope = {"type": "http", "method": "POST", "path": "/api/replay/run",
             "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    with pytest.raises(FaultlineError) as caught:
        require_admin_in_public_mode(Request(scope))
    assert caught.value.status_code == status and caught.value.code == "ADMIN_TOKEN_REQUIRED"


@pytest.mark.parametrize("route", GATED)
def test_public_mode_with_the_admin_token_works(world, monkeypatch, route):
    pid = _saved_prediction(world)
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    resp = _call(world.client(), route, pid, {"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("mode", ["PUBLIC", "Public ", "staging", "pub"])
def test_any_mode_other_than_local_is_gated(world, monkeypatch, mode):
    """Fail closed: an unrecognised FAULTLINE_MODE is treated as public, never as local."""
    pid = _saved_prediction(world)
    monkeypatch.setenv("FAULTLINE_MODE", mode)
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    if mode.strip().lower() not in ("public", "local"):
        # config.get_settings refuses an unknown mode at startup (PR #28); the route gate alone also says public.
        from config import ConfigError

        with pytest.raises(ConfigError):
            world.client()
        _assert_route_gate_refuses({}, 401)
        return
    _assert_refused(_call(world.client(), "reveal", pid), 401)


def test_public_mode_keeps_read_only_routes_open(world, monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    client = world.client()
    assert client.get("/api/cases").status_code == 200
    assert client.get(f"/api/cases/{EVENT}/evidence").status_code == 200


def test_openapi_documents_the_admin_refusals(world):
    doc = world.client().get("/openapi.json").json()
    for path in ("/api/replay/run", "/api/replay/{prediction_id}/reveal"):
        responses = doc["paths"][path]["post"]["responses"]
        assert {"401", "403"} <= set(responses), path
