"""App wiring: typed errors and CORS limited to the local web origin."""

from __future__ import annotations

from fastapi.testclient import TestClient

from errors import FaultlineError
from main import create_app
from models import ErrorCode


def test_faultline_error_is_machine_readable():
    app = create_app()

    @app.get("/_test/boom")
    def boom():
        raise FaultlineError(ErrorCode.MODEL_UNAVAILABLE, "Ollama is not reachable.", status_code=503)

    resp = TestClient(app).get("/_test/boom")
    assert resp.status_code == 503
    assert resp.json() == {"code": "MODEL_UNAVAILABLE", "message": "Ollama is not reachable."}


def test_cors_allows_local_web_origin_only(monkeypatch):
    monkeypatch.delenv("FAULTLINE_WEB_ORIGIN", raising=False)
    client = TestClient(create_app())
    headers = {"Access-Control-Request-Method": "GET"}
    ok = client.options("/api/health", headers={**headers, "Origin": "http://localhost:3000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/api/health", headers={**headers, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_every_api_route_declares_response_model():
    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/"):
            assert getattr(route, "response_model", None) is not None, path
