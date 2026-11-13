"""/openapi.json stays valid and describes the Wave 1 routes, so apps/web can generate types from it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app


def _schema() -> dict:
    resp = TestClient(create_app()).get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


def _ref(schema: dict, ref: str) -> dict:
    name = ref.rsplit("/", 1)[-1]
    return schema["components"]["schemas"][name]


def test_routes_are_published():
    paths = _schema()["paths"]
    assert "post" in paths["/api/simulate"]
    for path in ("/api/scenarios", "/api/vc-lenses", "/api/cases", "/api/health"):
        assert "get" in paths[path], path


def test_simulate_contract_in_schema():
    schema = _schema()
    op = schema["paths"]["/api/simulate"]["post"]
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    body = _ref(schema, ok["$ref"])
    assert set(body["properties"]) == {"provenance", "business_provenance", "baseline", "result", "deltas"}
    assert set(body["required"]) == {"provenance", "business_provenance", "baseline", "result", "deltas"}
    err = op["responses"]["422"]["content"]["application/json"]["schema"]
    assert set(_ref(schema, err["$ref"])["properties"]) == {"code", "message", "errors"}
    req = op["requestBody"]["content"]["application/json"]["schema"]
    assert set(_ref(schema, req["$ref"])["properties"]) == {"scenario_id", "shock", "plan"}


def test_vc_lenses_as_of_is_an_optional_query_param():
    op = _schema()["paths"]["/api/vc-lenses"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert params["as_of"]["in"] == "query"
    assert params["as_of"]["required"] is False


def test_no_default_validation_error_shape_on_new_routes():
    schema = _schema()
    for path in ("/api/simulate", "/api/vc-lenses"):
        for op in schema["paths"][path].values():
            ref = op["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/RouteErrorBody"), (path, ref)
