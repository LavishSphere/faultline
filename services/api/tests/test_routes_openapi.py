"""/openapi.json stays valid and describes the Wave 1 routes, so apps/web can generate types from it."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

import routes
from main import create_app
from models import ErrorCode
from routes import RouteErrorBody

ROUTES_DIR = Path(__file__).resolve().parent.parent / "routes"


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
    keys = {
        "provenance", "business_provenance", "baseline", "result", "deltas",
        "min_cash_floor", "first_week_below_floor", "weeks_below_floor",  # #157 (F2): floor C_min, §4.1/§10
    }
    assert set(body["properties"]) == keys
    assert set(body["required"]) == keys
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


# --------------------------------------------------------------------------- one error-code enum (issue #52)

ROUTE_CODES = {"VALIDATION_ERROR", "INFEASIBLE_INPUT", "DATA_INVALID", "DATA_UNAVAILABLE"}
PROVIDER_CODES = {"MODEL_UNAVAILABLE", "MODEL_OUTPUT_INVALID", "PROMPT_TOO_LONG", "PROMPT_NOT_VERIFIED"}


def test_every_error_code_lives_in_models_error_code():
    assert {c.value for c in ErrorCode} >= ROUTE_CODES | PROVIDER_CODES
    assert all(c.name == c.value for c in ErrorCode)


def test_routes_use_models_error_code_and_define_no_enum_of_their_own():
    assert routes.ErrorCode is ErrorCode
    assert not hasattr(routes, "RouteErrorCode")
    assert RouteErrorBody.model_fields["code"].annotation is ErrorCode
    for path in ROUTES_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "RouteErrorCode" not in source, path.name
        assert not re.search(r"^class \w*Code\w*\((Str)?Enum\)", source, re.MULTILINE), path.name


def test_route_error_body_code_enum_in_schema_is_error_code():
    schema = _schema()
    code = _ref(schema, "#/components/schemas/RouteErrorBody")["properties"]["code"]
    enum = _ref(schema, code["$ref"])["enum"] if "$ref" in code else code["enum"]
    assert set(enum) == {c.value for c in ErrorCode}


# --------------------------------------------------------------------------- scorable in the lens schema (issue #52)


def test_lens_quote_schemas_publish_optional_boolean_scorable():
    components = _schema()["components"]["schemas"]
    quote_schemas = {name: s for name, s in components.items() if name.startswith("LensQuote")}
    assert quote_schemas
    for name, s in quote_schemas.items():
        assert s["properties"]["scorable"]["type"] == "boolean", name
        assert "scorable" not in s.get("required", []), name


def test_excluded_not_yet_public_is_nullable_in_schema():
    schema = _schema()
    prop = _ref(schema, "#/components/schemas/VcLensesPointInTime")["properties"]["excluded_not_yet_public"]
    types = {opt.get("type") for opt in prop.get("anyOf", [prop])}
    assert types == {"integer", "null"}
