"""Deployment boundary (#13): CORS allowlist, public vs local mode, admin-gated inference,
per-IP rate limiting, request body limit, and the committed deploy files.

CORS only constrains browsers, so every protection here is tested at the ASGI level too.
No test touches the network: Ollama is pointed at a closed loopback port and most requests
hit throwaway routes registered on a fresh app.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from main import create_app

REPO = Path(__file__).resolve().parents[3]
PUBLIC_ORIGIN = "https://faultline.example.org"
OTHER_ORIGIN = "https://evil.example"
LOCAL_ORIGIN = "http://localhost:3000"
# Deliberately not key-shaped (CI secrets scan); long enough to pass MIN_ADMIN_TOKEN_LEN.
ADMIN_TOKEN = "test-admin-token-not-a-real-secret-0123456789"

ENV_VARS = (
    "FAULTLINE_MODE",
    "FAULTLINE_CORS_ORIGINS",
    "FAULTLINE_PUBLIC_ORIGIN",
    "FAULTLINE_WEB_ORIGIN",
    "FAULTLINE_ADMIN_TOKEN",
    "FAULTLINE_RATE_LIMIT_PER_MIN",
    "FAULTLINE_MAX_BODY_BYTES",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))


def _app_with_probe_routes() -> FastAPI:
    """A real app plus throwaway routes: one stands in for the not-yet-built replay route."""
    app = create_app()

    @app.get("/_test/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/_test/echo")
    async def echo(payload: dict) -> dict[str, int]:
        return {"keys": len(payload)}

    @app.post("/api/replay/_probe")  # under the gated /api/replay prefix; the real run route needs a body
    def fake_replay_run() -> dict[str, str]:
        return {"reached": "replay-run handler"}

    return app


def _preflight(client: TestClient, origin: str, method: str = "GET"):
    return client.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": method})


# --------------------------------------------------------------------------- mode


def test_default_mode_is_local_for_the_dev_process():
    assert config.get_settings().mode == "local"


def test_invalid_mode_fails_loudly(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "prod")
    with pytest.raises(config.ConfigError):
        config.get_settings()


@pytest.mark.parametrize("mode", ["public", "local"])
def test_every_response_reports_mode_header(monkeypatch, mode):
    monkeypatch.setenv("FAULTLINE_MODE", mode)
    resp = TestClient(create_app()).get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["x-faultline-mode"] == mode


def test_mode_header_is_readable_cross_origin(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", PUBLIC_ORIGIN)
    resp = TestClient(create_app()).get("/api/health", headers={"Origin": PUBLIC_ORIGIN})
    exposed = {h.strip().lower() for h in resp.headers["access-control-expose-headers"].split(",")}
    assert "x-faultline-mode" in exposed


# --------------------------------------------------------------------------- CORS


def test_public_cors_allows_configured_origin_and_rejects_others(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", f"{PUBLIC_ORIGIN}, https://second.example.org/")
    client = TestClient(create_app())

    ok = _preflight(client, PUBLIC_ORIGIN)
    assert ok.headers.get("access-control-allow-origin") == PUBLIC_ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    # trailing slash in the env value is normalised away
    assert _preflight(client, "https://second.example.org").headers.get("access-control-allow-origin")

    for origin in (OTHER_ORIGIN, LOCAL_ORIGIN, "http://127.0.0.1:3000", "null"):
        assert "access-control-allow-origin" not in _preflight(client, origin).headers, origin

    simple = client.get("/api/health", headers={"Origin": OTHER_ORIGIN})
    assert "access-control-allow-origin" not in simple.headers


def test_cors_origins_are_lowercased_so_they_match_browsers(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", "HTTPS://FaultLine.Example.org, https://ports.example.org:8443")
    assert config.get_settings().cors_origins == (PUBLIC_ORIGIN, "https://ports.example.org:8443")
    client = TestClient(create_app())
    assert _preflight(client, PUBLIC_ORIGIN).headers.get("access-control-allow-origin") == PUBLIC_ORIGIN


def test_public_cors_default_origin_is_the_public_site(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    settings = config.get_settings()
    assert settings.cors_origins == (config.DEFAULT_PUBLIC_ORIGIN,)
    assert config.DEFAULT_PUBLIC_ORIGIN.startswith("https://")


def test_public_origin_env_moves_the_default(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_PUBLIC_ORIGIN", PUBLIC_ORIGIN)
    assert config.get_settings().cors_origins == (PUBLIC_ORIGIN,)


def test_local_mode_adds_localhost(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    client = TestClient(create_app())
    for origin in (LOCAL_ORIGIN, "http://127.0.0.1:3000", config.DEFAULT_PUBLIC_ORIGIN):
        assert _preflight(client, origin).headers.get("access-control-allow-origin") == origin
    assert "access-control-allow-origin" not in _preflight(client, OTHER_ORIGIN).headers


def test_cors_methods_are_get_and_post_only(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", PUBLIC_ORIGIN)
    client = TestClient(create_app())
    assert _preflight(client, PUBLIC_ORIGIN, "POST").status_code == 200
    for method in ("DELETE", "PUT", "PATCH"):
        resp = _preflight(client, PUBLIC_ORIGIN, method)
        assert resp.status_code == 400, method


def test_admin_header_is_not_allowed_cross_origin(monkeypatch):
    """The admin token is for the lead's terminal, never a browser: Authorization is not a CORS-allowed header."""
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", PUBLIC_ORIGIN)
    resp = TestClient(create_app()).options(
        "/api/replay/run",
        headers={
            "Origin": PUBLIC_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "null",
        "faultline.example.org",
        "https://faultline.example.org/app",
        "ftp://x.example",
        "http://plain.example",
        "https://x.example:abc",
        "https://x.example:99999",
    ],
)
def test_public_mode_rejects_unsafe_cors_entries(monkeypatch, bad):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", bad)
    with pytest.raises(config.ConfigError):
        config.get_settings()


# --------------------------------------------------------------------------- admin-gated inference


def _public_client(monkeypatch, token: str | None = ADMIN_TOKEN) -> TestClient:
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    if token is not None:
        monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", token)
    return TestClient(_app_with_probe_routes())


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token-wrong-token-wrong-token-0000"},
        {"Authorization": ADMIN_TOKEN},  # missing Bearer scheme
        {"Authorization": f"Basic {ADMIN_TOKEN}"},
        {"X-Faultline-Admin-Token": ADMIN_TOKEN},  # only Authorization: Bearer is accepted
    ],
)
def test_public_mode_refuses_replay_run_without_valid_token(monkeypatch, headers):
    resp = _public_client(monkeypatch).post("/api/replay/run", json={}, headers=headers)
    # Same statuses as the route-level gate: 401 when no bearer token is presented, 403 when it is wrong.
    assert resp.status_code == (403 if headers.get("Authorization", "").startswith("Bearer ") else 401)
    body = resp.json()
    assert body["code"] == "ADMIN_TOKEN_REQUIRED"
    assert ADMIN_TOKEN not in resp.text


@pytest.mark.parametrize(
    "path",
    ["/api/replay/run/", "/api/replay/run/some-case", "/API/replay/run", "/api//replay/run", "/api/replay/x/reveal",
     "/api/explore/search", "/API/Explore/analyze/", "/api/benchmark/compute", "/api//benchmark/compute/"],
)
def test_public_mode_gate_covers_path_variants(monkeypatch, path):
    resp = _public_client(monkeypatch).post(path, json={}, follow_redirects=False)
    assert resp.status_code == 401, path
    resp = _public_client(monkeypatch).post(path, json={}, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 403, path


def test_every_registered_inference_route_is_gated(monkeypatch):
    """Guards future routers: a replay route that runs the model must sit under the gated prefix."""
    from main import is_admin_gated

    # The OpenAPI schema (local mode) lists every route, also inside included routers (create_app().routes
    # holds lazy wrappers on recent FastAPI). tests/test_public_mode_routes.py classifies all of them.
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    paths = list(create_app().openapi()["paths"])
    assert "/api/replay/run" in paths
    for path in paths:
        if "/replay" in path and re.search(r"/run\b", path):
            assert is_admin_gated(path), f"{path} runs inference but is not admin-gated in public mode"


def test_public_mode_gate_applies_to_every_method(monkeypatch):
    client = _public_client(monkeypatch)
    assert client.get("/api/replay/run").status_code == 401


def test_public_mode_with_valid_token_reaches_handler(monkeypatch):
    resp = _public_client(monkeypatch).post(
        "/api/replay/_probe", json={}, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"reached": "replay-run handler"}


@pytest.mark.parametrize("token", [None, ""])
def test_public_mode_without_token_configured_always_refuses(monkeypatch, token):
    client = _public_client(monkeypatch, token=token)
    resp = client.post("/api/replay/run", json={}, headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 403


def test_public_mode_weak_token_fails_loudly(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", "short-token")
    with pytest.raises(config.ConfigError, match="shorter than"):
        create_app()
    assert not config.admin_token_matches("short-token")  # and it would never match anyway


def test_public_mode_disables_api_docs(monkeypatch):
    client = _public_client(monkeypatch)
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path
    assert client.get("/api/health").status_code == 200


def test_local_mode_keeps_api_docs(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    client = TestClient(create_app())
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_public_mode_leaves_deterministic_routes_open(monkeypatch):
    client = _public_client(monkeypatch)
    assert client.get("/_test/ping").status_code == 200
    assert client.post("/_test/echo", json={"a": 1}).json() == {"keys": 1}


def test_local_mode_replay_run_needs_no_token(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    resp = TestClient(_app_with_probe_routes()).post("/api/replay/_probe", json={})
    assert resp.status_code == 200


def test_admin_token_never_echoed(monkeypatch):
    client = _public_client(monkeypatch)
    resp = client.get("/api/health")
    assert ADMIN_TOKEN not in resp.text
    assert all(ADMIN_TOKEN not in v for v in resp.headers.values())
    assert not hasattr(config.get_settings(), "admin_token")


# --------------------------------------------------------------------------- rate limit


def test_rate_limit_defaults(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    assert config.get_settings().rate_limit_per_min == config.DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN > 0
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    assert config.get_settings().rate_limit_per_min == 0  # off for the laptop demo


def test_rate_limit_returns_429_per_ip(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_RATE_LIMIT_PER_MIN", "3")
    app = _app_with_probe_routes()
    first = TestClient(app, client=("198.51.100.1", 40000))
    for _ in range(3):
        assert first.get("/_test/ping").status_code == 200
    limited = first.get("/_test/ping")
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.headers["x-faultline-mode"] == "public"
    # a different client IP has its own bucket
    assert TestClient(app, client=("198.51.100.2", 40000)).get("/_test/ping").status_code == 200


def test_rate_limited_response_keeps_cors_headers(monkeypatch):
    """The browser must be able to read the 429 (so the UI can say why), not see an opaque CORS failure."""
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_CORS_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("FAULTLINE_RATE_LIMIT_PER_MIN", "1")
    client = TestClient(_app_with_probe_routes(), client=("198.51.100.3", 40000))
    client.get("/_test/ping", headers={"Origin": PUBLIC_ORIGIN})
    resp = client.get("/_test/ping", headers={"Origin": PUBLIC_ORIGIN})
    assert resp.status_code == 429
    assert resp.headers.get("access-control-allow-origin") == PUBLIC_ORIGIN


def test_rate_limit_keys_ipv6_by_slash_64(monkeypatch):
    from main import rate_limit_key

    assert rate_limit_key("2001:db8:1:2::1") == rate_limit_key("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert rate_limit_key("2001:db8:1:3::1") != rate_limit_key("2001:db8:1:2::1")
    assert rate_limit_key("::ffff:198.51.100.4") == "198.51.100.4"
    assert rate_limit_key("198.51.100.4") == "198.51.100.4"
    assert rate_limit_key("unknown") == "unknown"

    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_RATE_LIMIT_PER_MIN", "2")
    app = _app_with_probe_routes()
    for host in ("2001:db8:5:5::1", "2001:db8:5:5::2"):
        assert TestClient(app, client=(host, 40000)).get("/_test/ping").status_code == 200
    # a third address in the same /64 shares the bucket
    assert TestClient(app, client=("2001:db8:5:5::3", 40000)).get("/_test/ping").status_code == 429


def test_token_bucket_refills_with_time():
    from main import TokenBucketLimiter

    now = [1000.0]
    limiter = TokenBucketLimiter(per_minute=60, clock=lambda: now[0])
    for _ in range(60):
        assert limiter.check("a")[0]
    allowed, retry_after = limiter.check("a")
    assert not allowed and retry_after >= 1
    now[0] += 1.0  # 60/min = 1 token per second
    assert limiter.check("a")[0]


def test_token_bucket_memory_is_bounded():
    from main import TokenBucketLimiter

    limiter = TokenBucketLimiter(per_minute=5, max_clients=100)
    for i in range(1000):
        limiter.check(f"10.0.{i // 256}.{i % 256}")
    assert len(limiter) <= 100


@pytest.mark.parametrize(
    ("var", "value"),
    [("FAULTLINE_RATE_LIMIT_PER_MIN", v) for v in ("-1", "abc", "1.5")] + [("FAULTLINE_MAX_BODY_BYTES", "0")],
)
def test_bad_numeric_limits_fail_loudly(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(config.ConfigError):
        config.get_settings()


# --------------------------------------------------------------------------- body size


def test_body_limit_by_content_length(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MAX_BODY_BYTES", "64")
    client = TestClient(_app_with_probe_routes())
    assert client.post("/_test/echo", json={"a": 1}).status_code == 200
    resp = client.post("/_test/echo", json={"a": "x" * 200})
    assert resp.status_code == 413
    assert resp.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_body_limit_without_content_length(monkeypatch):
    """Chunked uploads carry no Content-Length; the limit must count streamed bytes."""
    monkeypatch.setenv("FAULTLINE_MAX_BODY_BYTES", "64")
    client = TestClient(_app_with_probe_routes())

    def chunks():
        yield b'{"a": "'
        for _ in range(20):
            yield b"x" * 10
        yield b'"}'

    resp = client.post("/_test/echo", content=chunks(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


def test_body_limit_default_is_present():
    assert 0 < config.get_settings().max_body_bytes <= 1024 * 1024


# --------------------------------------------------------------------------- committed deploy files


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_pages_workflow_deploys_only_on_push_to_main():
    wf = _read(".github/workflows/pages.yml")
    on_block = wf.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert re.search(r"push:\s*\n\s*branches:\s*\[\s*main\s*\]", on_block), on_block
    for trigger in ("pull_request", "workflow_dispatch", "schedule", "release"):
        assert trigger not in on_block
    assert "name: github-pages" in wf
    assert "github.ref == 'refs/heads/main'" in wf
    assert "vars.FAULTLINE_PUBLIC_ORIGIN" in wf and "vars.FAULTLINE_API_HOST" in wf
    assert "NEXT_PUBLIC_API_BASE" in wf and ".nojekyll" in wf and "CNAME" in wf


def test_caddy_has_body_limit_and_proxies_to_api():
    caddy = _read("deploy/Caddyfile")
    assert "{$FAULTLINE_API_HOST}" in caddy
    assert re.search(r"request_body\s*\{[^}]*max_size 64KiB", caddy)  # 65,536 bytes, same as the app default
    assert config.DEFAULT_MAX_BODY_BYTES == 64 * 1024
    assert re.search(r"reverse_proxy api:8000\s*\{[^}]*header_up X-Forwarded-For \{remote_host\}", caddy)


def test_compose_hardening_present():
    compose = _read("deploy/docker-compose.yml")
    assert "FAULTLINE_MODE: public" in compose
    assert "read_only: true" in compose
    assert "FAULTLINE_RATE_LIMIT_PER_MIN" in compose and "FAULTLINE_MAX_BODY_BYTES" in compose
    assert 'profiles: ["ollama"]' in compose
    assert "internal: true" in compose
    # only Caddy publishes ports, and only 80/443
    published = re.findall(r'^\s*-\s*"(\d+):(\d+)(?:/\w+)?"\s*$', compose, re.M)
    assert published and {host for host, _ in published} <= {"80", "443"}
    assert "11434:" not in compose and "8000:" not in compose
    ollama = compose.split("\n  ollama:", 1)[1].split("\nnetworks:", 1)[0]
    assert "cap_drop: [ALL]" in ollama and "no-new-privileges:true" in ollama and "pids:" in ollama


def test_api_image_runs_as_non_root_in_public_mode():
    dockerfile = _read("deploy/api.Dockerfile")
    assert re.search(r"^USER\s+\d+", dockerfile, re.M)
    assert "FAULTLINE_MODE=public" in dockerfile


ALLOWED_IPS = {"127.0.0.1", "0.0.0.0"}
DOCUMENTATION_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
DEPLOY_FILES = [
    "deploy/docker-compose.yml",
    "deploy/Caddyfile",
    "deploy/api.Dockerfile",
    "deploy/.env.example",
    "scripts/deploy-api.sh",
    "docs/DEPLOY.md",
    ".github/workflows/pages.yml",
]


@pytest.mark.parametrize("rel", DEPLOY_FILES)
def test_no_server_addresses_or_credentials_committed(rel):
    text = _read(rel)
    for candidate in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        # Any other literal (public or LAN) could identify the server.
        documentation = any(ip in net for net in DOCUMENTATION_NETS)
        assert candidate in ALLOWED_IPS or documentation, f"{rel}: IP literal {candidate}"
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text)
    assert not re.search(r"\b[\w.-]+@(?:\d{1,3}\.){3}\d{1,3}\b", text), "user@ip SSH target"
    assert not re.search(r"^FAULTLINE_ADMIN_TOKEN=\S+", text, re.M), "admin token value committed"
