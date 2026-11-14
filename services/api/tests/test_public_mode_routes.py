"""Public mode covers EVERY route (#13): one classification table, enforced at the edge and inside the routes.

`main.PUBLIC_MODE_ROUTES` is the table; docs/DEPLOY.md mirrors it. These tests walk the live OpenAPI schema (and the
raw route list, which also sees `include_in_schema=False` routes), so a new route that nobody classified fails here
instead of silently shipping as public.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
from main import ADMIN, PUBLIC, PUBLIC_MODE_ROUTES, create_app, is_admin_gated

DEPLOY_MD = Path(__file__).resolve().parents[3] / "docs" / "DEPLOY.md"
TOKEN = "public-mode-routes-test-" + "t" * 24  # not key-shaped (CI secrets scan); >= 32 characters
ORIGIN = "https://faultline.khayrul.com"


@pytest.fixture
def local_env(monkeypatch):
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_CORS_ORIGINS", "FAULTLINE_PUBLIC_ORIGIN",
                 "FAULTLINE_RATE_LIMIT_PER_MIN", "FAULTLINE_MAX_BODY_BYTES", "TAVILY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def public_env(local_env):
    local_env.setenv("FAULTLINE_MODE", "public")
    local_env.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    local_env.setenv("FAULTLINE_PUBLIC_ORIGIN", ORIGIN)
    return local_env


def _openapi_routes() -> set[tuple[str, str]]:
    schema = create_app().openapi()  # local mode: the docs routes exist, the schema is complete
    return {(m.upper(), path) for path, ops in schema["paths"].items() for m in ops}


def _api_routes(routes, prefix: str = ""):
    """Every APIRoute with its full path, also inside included routers (FastAPI >= 0.16x wraps them lazily)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _api_routes(inner.routes, prefix + (getattr(route.include_context, "prefix", "") or ""))


def _registered_routes() -> set[tuple[str, str]]:
    out = set()
    for path, route in _api_routes(create_app().routes):
        out |= {(m, path) for m in route.methods if m not in ("HEAD", "OPTIONS")}
    return out


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_every_openapi_route_is_classified(local_env):
    routes = _openapi_routes()
    assert routes == set(PUBLIC_MODE_ROUTES), (
        f"unclassified: {sorted(routes - set(PUBLIC_MODE_ROUTES))}; "
        f"stale table rows: {sorted(set(PUBLIC_MODE_ROUTES) - routes)}"
    )
    assert set(PUBLIC_MODE_ROUTES.values()) <= {ADMIN, PUBLIC}


def test_no_hidden_route_escapes_the_table(local_env):
    assert _registered_routes() == set(PUBLIC_MODE_ROUTES)


def test_edge_prefixes_agree_with_the_table(local_env):
    """The edge gate refuses exactly the admin rows, and no public row sits under a gated prefix."""
    for (_method, path), kind in PUBLIC_MODE_ROUTES.items():
        assert is_admin_gated(_concrete(path)) == (kind == ADMIN), (path, kind)


def test_admin_routes_also_gate_inside_the_route():
    """Defence in depth: each admin route carries the shared route-level gate, not only the edge prefix."""
    from routes.replay import require_admin_in_public_mode

    seen = 0
    for path, route in _api_routes(create_app().routes):
        admin = any(PUBLIC_MODE_ROUTES.get((m, path)) == ADMIN for m in route.methods)
        deps = {d.call for d in route.dependant.dependencies}
        gated_class = type(route).__name__ == "AdminGatedRoute"
        assert admin == (require_admin_in_public_mode in deps or gated_class), path
        seen += 1
    assert seen == len(PUBLIC_MODE_ROUTES)  # the walk is not vacuous


@pytest.mark.parametrize("key", sorted(PUBLIC_MODE_ROUTES), ids=lambda k: f"{k[0]} {k[1]}")
def test_public_mode_behaviour_matches_the_classification(public_env, key):
    method, path = key
    client = TestClient(create_app())
    url = _concrete(path)
    resp = client.request(method, url, json={} if method == "POST" else None)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if PUBLIC_MODE_ROUTES[key] == ADMIN:
        assert resp.status_code == 401 and body.get("code") == "ADMIN_TOKEN_REQUIRED", (key, resp.text)
        wrong = client.request(method, url, json={} if method == "POST" else None,
                               headers={"Authorization": "Bearer " + "w" * 40})
        assert wrong.status_code == 403 and wrong.json()["code"] == "ADMIN_TOKEN_REQUIRED"
    else:
        assert resp.status_code not in (401, 403) and body.get("code") != "ADMIN_TOKEN_REQUIRED", (key, resp.text)
    assert resp.headers["x-faultline-mode"] == "public"
    assert TOKEN not in resp.text


def test_deploy_md_table_matches_the_code():
    text = DEPLOY_MD.read_text(encoding="utf-8")
    rows = dict(
        ((m, p), kind)
        for m, p, kind in re.findall(r"^\| `(GET|POST) (/api/[^`]*)` \| (admin|public) \|", text, re.M)
    )
    assert rows == PUBLIC_MODE_ROUTES


# ---------------------------------------------------------------- limits and CORS on today's public routes


def test_body_cap_applies_to_new_public_post_routes(public_env):
    client = TestClient(create_app())
    big = b"{" + b" " * (70 * 1024) + b"}"
    for path in ("/api/optimize", "/api/decision", "/api/simulate"):
        resp = client.post(path, content=big, headers={"content-type": "application/json"})
        assert resp.status_code == 413 and resp.json()["code"] == "PAYLOAD_TOO_LARGE", path


def test_rate_limit_applies_to_new_public_routes(public_env):
    public_env.setenv("FAULTLINE_RATE_LIMIT_PER_MIN", "3")
    client = TestClient(create_app())
    codes = [client.get("/api/judge-challenges").status_code for _ in range(3)]
    codes.append(client.get("/api/integrity").status_code)
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_cors_allows_the_public_origin_on_new_routes_and_nothing_else(public_env):
    client = TestClient(create_app())
    for path in ("/api/optimize", "/api/decision", "/api/benchmark", "/api/judge-challenges"):
        ok = client.options(path, headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                           "Access-Control-Request-Headers": "content-type"})
        assert ok.headers.get("access-control-allow-origin") == ORIGIN, path
        bad = client.options(path, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in bad.headers, path
    # A browser can never send the admin token: Authorization is not an allowed request header.
    pre = client.options("/api/replay/run", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 400 or "authorization" not in pre.headers.get("access-control-allow-headers", "").lower()


def test_edge_error_codes_match_the_api_contract():
    from models import ErrorCode

    assert main.EdgeErrorCode.ADMIN_TOKEN_REQUIRED.value == ErrorCode.ADMIN_TOKEN_REQUIRED.value
    assert main.EdgeErrorCode.RATE_LIMITED.value == ErrorCode.RATE_LIMITED.value
