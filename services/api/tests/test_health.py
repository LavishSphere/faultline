"""/api/health: must answer 200 with Ollama down, and must never echo secret values.

No test here touches the public network: Ollama is either replaced by an httpx.MockTransport
or pointed at a closed loopback port.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from main import create_app
from routes.health import get_ollama_transport

# Fake values, deliberately NOT shaped like real keys (CI secrets scan forbids key-shaped literals).
SECRET_ANTHROPIC = "fake-anthropic-value-should-never-appear-0001"
SECRET_TAVILY = "fake-tavily-value-should-never-appear-0002"


def _client_with_transport(transport: httpx.AsyncBaseTransport | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_ollama_transport] = lambda: transport
    return TestClient(app)


def _down_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.MockTransport(handler)


def _tags_transport(names: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": n, "model": n} for n in names]})

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "OLLAMA_BASE_URL", "FAULTLINE_OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))


def test_health_ollama_down_still_200():
    resp = _client_with_transport(_down_transport()).get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ollama"] is False
    assert body["model_ready"] is False
    assert body["ollama_status"]["reachable"] is False
    assert body["ollama_status"]["models"] == []
    assert body["ollama_status"]["required_model_present"] is False
    assert body["ollama_status"]["error"]
    assert any("Ollama" in n for n in body["notices"])


def test_health_ollama_down_real_transport_closed_port(monkeypatch):
    """Default transport (no override) against a closed loopback port: no hang, still 200."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    resp = TestClient(create_app()).get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ollama"] is False


def test_health_ollama_up_lists_tags_and_model_readiness(monkeypatch):
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "llama3.1:8b")
    body = _client_with_transport(_tags_transport(["llama3.1:8b", "gemma2:2b"])).get("/api/health").json()
    assert body["ollama"] is True
    assert body["ollama_status"]["models"] == ["gemma2:2b", "llama3.1:8b"]
    assert body["ollama_status"]["required_model"] == "llama3.1:8b"
    assert body["ollama_status"]["required_model_present"] is True
    assert body["model_ready"] is True


def test_health_ollama_up_but_model_missing(monkeypatch):
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "llama3.1:8b")
    body = _client_with_transport(_tags_transport(["gemma2:2b"])).get("/api/health").json()
    assert body["ollama"] is True
    assert body["ollama_status"]["required_model_present"] is False
    assert body["model_ready"] is False
    assert any("llama3.1:8b" in n for n in body["notices"])


def test_health_untagged_model_matches_latest(monkeypatch):
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "mistral")
    body = _client_with_transport(_tags_transport(["mistral:latest"])).get("/api/health").json()
    assert body["ollama_status"]["required_model_present"] is True


def test_health_ollama_garbage_response_is_not_reachable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not ollama</html>")

    body = _client_with_transport(httpx.MockTransport(handler)).get("/api/health").json()
    assert body["ollama"] is False
    assert body["ollama_status"]["models"] == []


def test_health_keys_absent_are_false():
    body = _client_with_transport(_down_transport()).get("/api/health").json()
    assert body["optional_keys"] == {"anthropic_api_key": False, "tavily_api_key": False}
    assert any("ANTHROPIC_API_KEY" in n for n in body["notices"])
    assert any("TAVILY_API_KEY" in n for n in body["notices"])


def test_health_keys_present_are_booleans_never_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_ANTHROPIC)
    monkeypatch.setenv("TAVILY_API_KEY", SECRET_TAVILY)
    resp = _client_with_transport(_down_transport()).get("/api/health")
    body = resp.json()
    assert body["optional_keys"] == {"anthropic_api_key": True, "tavily_api_key": True}
    assert SECRET_ANTHROPIC not in resp.text
    assert SECRET_TAVILY not in resp.text
    # not even a fragment of the values
    assert "fake-anthropic" not in resp.text and "fake-tavily" not in resp.text


def test_health_blank_key_counts_as_absent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    body = _client_with_transport(_down_transport()).get("/api/health").json()
    assert body["optional_keys"]["anthropic_api_key"] is False


def test_health_manifest_missing_is_null():
    body = _client_with_transport(_down_transport()).get("/api/health").json()
    assert body["data_dir_present"] is False
    assert body["data_manifest_sha256"] is None
    assert any("manifest" in n.lower() and "NOT AVAILABLE" in n for n in body["notices"])


def test_health_manifest_hash_is_sha256_of_file_bytes(tmp_path, monkeypatch):
    data_dir = tmp_path / "fixture_data"
    data_dir.mkdir()
    raw = json.dumps({"files": {"a.json": "0" * 64}}, sort_keys=True).encode()
    (data_dir / "manifest.json").write_bytes(raw)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data_dir))
    body = _client_with_transport(_down_transport()).get("/api/health").json()
    assert body["data_dir_present"] is True
    assert body["data_manifest_sha256"] == hashlib.sha256(raw).hexdigest()


def test_health_does_not_leak_ollama_base_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://user:hunter2@10.1.2.3:11434")
    resp = _client_with_transport(_down_transport()).get("/api/health")
    assert "hunter2" not in resp.text


@pytest.mark.parametrize("bad_url", ["http://[::1", "http://localhost:notaport"])
def test_health_malformed_ollama_base_url_is_200_not_500(monkeypatch, bad_url):
    """httpx.InvalidURL is not an httpx.HTTPError; it must still be reported as unreachable."""
    monkeypatch.setenv("OLLAMA_BASE_URL", bad_url)
    resp = TestClient(create_app()).get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama"] is False
    assert body["ollama_status"]["error"] == "Ollama not reachable at OLLAMA_BASE_URL (InvalidURL)."
