"""Mock internal data room for the SYNTHETIC demo business (#209).

Serves ``<FAULTLINE_DATA_DIR>/internal/<table>.json``, written by ``scripts/gen_internal_data.py`` from a fixed seed
and anchored on ``demo_business.json`` (same weekly sales, payroll, opex, inventory, debt terms). Every row is
SYNTHETIC (mock internal data) about a fictional company; nothing is a real ledger.

Routes (public in public mode, like /api/simulate: read-only, deterministic):
- ``GET /api/internal-data``: the tables with their description, schema and row count.
- ``GET /api/internal-data/{table}?limit=``: the first ``limit`` rows of one table.

``query_rows`` is the engine behind the chat's ``query_internal_data`` tool: filters, group_by and the aggregate
(sum | mean | count | min | max) are computed here in Python, so a model never adds numbers up itself.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from config import Settings, get_settings
from models import ErrorCode
from routes import CodedRoute, RouteError, RouteErrorBody, error_responses, read_json

router = APIRouter(tags=["internal-data"], route_class=CodedRoute)

INTERNAL_DIR = "internal"
TABLES: tuple[str, ...] = ("general_ledger", "ar_aging", "ap_schedule", "payroll", "inventory", "customers", "debt",
                           "contracts")
LABEL = "SYNTHETIC (mock internal data)"
MAX_QUERY_ROWS = 50
MAX_ROUTE_ROWS = 1000
Aggregate = Literal["sum", "mean", "count", "min", "max"]
FilterOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"]


class InternalTableInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    row_count: int
    schema_: dict[str, str] = Field(alias="schema", serialization_alias="schema")


class InternalDataIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    provenance: Literal["SYNTHETIC"] = "SYNTHETIC"
    label: Literal["SYNTHETIC (mock internal data)"] = LABEL
    tables: list[InternalTableInfo]
    notes: list[str]


class InternalTableRows(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    provenance: Literal["SYNTHETIC"] = "SYNTHETIC"
    label: Literal["SYNTHETIC (mock internal data)"] = LABEL
    table: str
    description: str
    schema_: dict[str, str] = Field(alias="schema", serialization_alias="schema")
    row_count: int
    returned: int
    rows: list[dict[str, Any]]
    anchors: dict[str, Any] | None = Field(description="demo_business.json values the table is built to match.")


@lru_cache(maxsize=32)
def _load(path_str: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns  # part of the cache key only: an edited file is re-read
    path = Path(path_str)
    raw = read_json(path, f"{INTERNAL_DIR}/{path.name}")
    if not (isinstance(raw, dict) and raw.get("provenance") == "SYNTHETIC" and isinstance(raw.get("rows"), list)
            and isinstance(raw.get("schema"), dict)):
        raise RouteError(ErrorCode.DATA_INVALID, f"{INTERNAL_DIR}/{path.name} is not a SYNTHETIC data-room table.",
                         status_code=500)
    return raw


def load_table(settings: Settings, table: str) -> dict[str, Any] | None:
    """The table file, or None when it is not present (NOT AVAILABLE)."""
    if table not in TABLES:
        raise RouteError(ErrorCode.NOT_FOUND, f"Unknown table {table[:60]!r}. Tables: {', '.join(TABLES)}.",
                         status_code=404)
    path = settings.data_dir / INTERNAL_DIR / f"{table}.json"
    if not path.is_file():
        return None
    return _load(str(path), path.stat().st_mtime_ns)


def _require(settings: Settings, table: str) -> dict[str, Any]:
    data = load_table(settings, table)
    if data is None:
        raise RouteError(ErrorCode.DATA_UNAVAILABLE, f"Internal data table {table!r} is NOT AVAILABLE on this "
                         "server (run scripts/gen_internal_data.py).", status_code=503)
    return data


# --------------------------------------------------------------------------- query engine (chat tool)


class QueryError(ValueError):
    """A query the table cannot answer; the message goes back to the model as a tool error."""


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    return float(v)


def _match(value: Any, op: str, target: Any) -> bool:
    if op == "contains":
        return isinstance(value, str) and str(target).casefold() in value.casefold()
    if op in ("eq", "ne"):
        if isinstance(value, str) and isinstance(target, str):
            same = value.casefold() == target.casefold()
        elif _num(value) is not None and _num(target) is not None:
            same = math.isclose(float(value), float(target), abs_tol=1e-9)
        else:
            same = value == target
        return same if op == "eq" else not same
    a, b = _num(value), _num(target)
    if a is None or b is None:  # dates compare as ISO strings
        if isinstance(value, str) and isinstance(target, str):
            a_s, b_s = value, target
            return {"gt": a_s > b_s, "gte": a_s >= b_s, "lt": a_s < b_s, "lte": a_s <= b_s}[op]
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _aggregate(values: list[Any], how: str) -> float | int | None:
    if how == "count":
        return len(values)
    nums = [n for n in (_num(v) for v in values) if n is not None]
    if not nums:
        return None
    if how == "sum":
        return round(sum(nums), 2)
    if how == "mean":
        return round(sum(nums) / len(nums), 4)
    return round(min(nums) if how == "min" else max(nums), 4)


def query_rows(data: dict[str, Any], *, filters: list[dict[str, Any]] | None, group_by: str | None,
               aggregate: str | None, field: str | None, limit: int | None) -> dict[str, Any]:
    """Filter, then either return rows (no aggregate) or aggregate `field` (overall or per `group_by` value).
    Every figure is computed here; grouped sums also carry each group's share of the total."""
    schema = data["schema"]
    columns = list(schema)
    lim = MAX_QUERY_ROWS if limit is None else limit
    if not 1 <= lim <= MAX_QUERY_ROWS:
        raise QueryError(f"limit must be 1..{MAX_QUERY_ROWS}")
    for name, label in ((group_by, "group_by"), (field, "field")):
        if name is not None and name not in schema:
            raise QueryError(f"{label} {name[:60]!r} is not a column of {data['table']}. Columns: {columns}.")
    rows = list(data["rows"])
    for f in filters or []:
        col, op = f.get("field"), f.get("op")
        if col not in schema:
            raise QueryError(f"filter field {str(col)[:60]!r} is not a column of {data['table']}. Columns: {columns}.")
        if op not in FilterOp.__args__:  # type: ignore[attr-defined]
            raise QueryError(f"filter op must be one of {list(FilterOp.__args__)}")  # type: ignore[attr-defined]
        rows = [r for r in rows if _match(r.get(col), op, f.get("value"))]
    out: dict[str, Any] = {"table": data["table"], "rows_matched": len(rows), "computed_by": "Python (FAULTLINE), not "
                           "the model"}
    if aggregate is None:
        if group_by is not None or field is not None:
            raise QueryError("group_by and field need an aggregate (sum | mean | count | min | max)")
        out["rows"] = rows[:lim]
        out["returned"] = len(out["rows"])
        out["truncated"] = len(rows) > lim
        return out
    if aggregate not in Aggregate.__args__:  # type: ignore[attr-defined]
        raise QueryError(f"aggregate must be one of {list(Aggregate.__args__)}")  # type: ignore[attr-defined]
    if aggregate != "count" and field is None:
        raise QueryError(f"aggregate {aggregate!r} needs a numeric field")
    if field is not None and aggregate != "count" and rows and all(_num(r.get(field)) is None for r in rows):
        raise QueryError(f"field {field!r} is not numeric")
    values = [r.get(field) for r in rows] if field else rows
    out.update({"aggregate": aggregate, "field": field, "value": _aggregate(values, aggregate)})
    if group_by is None:
        return out
    groups: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r.get(group_by), []).append(r)
    total = out["value"]
    result = []
    for key, members in groups.items():
        g_values = [m.get(field) for m in members] if field else members
        value = _aggregate(g_values, aggregate)
        item: dict[str, Any] = {"group": key, "value": value, "rows": len(members)}
        if aggregate in ("sum", "count") and isinstance(total, int | float) and total and value is not None:
            item["share_of_total"] = round(value / total, 4)
        result.append(item)
    result.sort(key=lambda g: (g["value"] is None, -(g["value"] or 0)))
    out["group_by"] = group_by
    out["groups"] = result[:lim]
    out["groups_total"] = len(result)
    return out


# --------------------------------------------------------------------------- routes


@router.get("/internal-data", response_model=InternalDataIndex, response_model_by_alias=True,
            responses=error_responses(500), summary="Mock internal data room: tables (SYNTHETIC)")
def internal_data_index(settings: Annotated[Settings, Depends(get_settings)]) -> InternalDataIndex:
    infos, missing = [], []
    for name in TABLES:
        data = load_table(settings, name)
        if data is None:
            missing.append(name)
            continue
        infos.append(InternalTableInfo(name=name, description=str(data.get("description", "")),
                                       row_count=len(data["rows"]), schema=data["schema"]))
    notes = ["Every table is SYNTHETIC (mock internal data) for the fictional demo business, generated from a fixed "
             "seed by scripts/gen_internal_data.py and anchored on demo_business.json."]
    if missing:
        notes.append("NOT AVAILABLE on this server: " + ", ".join(missing) + ".")
    return InternalDataIndex(status="AVAILABLE" if infos else "NOT AVAILABLE", tables=infos, notes=notes)


_TABLE_ERRORS = {**error_responses(422, 500, 503),
                 404: {"model": RouteErrorBody, "description": "NOT_FOUND: unknown table"}}


@router.get("/internal-data/{table}", response_model=InternalTableRows, response_model_by_alias=True,
            responses=_TABLE_ERRORS, summary="Mock internal data room: one table (SYNTHETIC)")
def internal_data_table(
    table: str,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=MAX_ROUTE_ROWS)] = 100,
) -> InternalTableRows:
    data = _require(settings, table)
    rows = data["rows"][:limit]
    return InternalTableRows(table=table, description=str(data.get("description", "")), schema=data["schema"],
                             row_count=len(data["rows"]), returned=len(rows), rows=rows,
                             anchors=data.get("anchors"))


__all__ = ["LABEL", "MAX_QUERY_ROWS", "TABLES", "QueryError", "load_table", "query_rows", "router"]
