"""HTTP routers, plus the shared error contract for the data and simulation routes.

Every non-2xx response from a router that uses ``CodedRoute`` has the body ``RouteErrorBody``:
``{"code": <machine-readable code>, "message": <plain language>, "errors": [{loc, msg, type}, ...]}``.
That includes FastAPI request-validation failures, which would otherwise return ``{"detail": [...]}``
without a code. The conversion lives in the route class (not an app-level exception handler) so that
``main.py`` only registers routers.

Error details never echo input values (only locations, messages and error types), so a rejected
fixture file cannot leak its contents through an error response.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

NOT_AVAILABLE = "NOT AVAILABLE"


class RouteErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"  # request body / query failed validation (422)
    INFEASIBLE_INPUT = "INFEASIBLE_INPUT"  # valid shape, but financing that cannot happen (422)
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"  # a required data file is missing (503)
    DATA_INVALID = "DATA_INVALID"  # a data file exists but fails its schema (500)


class FieldIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loc: list[str | int] = Field(description='Where the problem is, e.g. ["body", "shock", "demand", "delta"].')
    msg: str
    type: str


class RouteErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: RouteErrorCode
    message: str = Field(description="Plain-language explanation, safe to show to the user.")
    errors: list[FieldIssue] = Field(default_factory=list)


class RouteError(Exception):
    def __init__(
        self,
        code: RouteErrorCode,
        message: str,
        status_code: int = 422,
        errors: list[FieldIssue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.errors = errors or []

    def response(self) -> JSONResponse:
        body = RouteErrorBody(code=self.code, message=self.message, errors=self.errors)
        return JSONResponse(status_code=self.status_code, content=body.model_dump(mode="json"))


def issues_from(errors: Iterable[Mapping[str, Any]], prefix: tuple[str | int, ...] = ()) -> list[FieldIssue]:
    """Pydantic/FastAPI error dicts -> FieldIssue, dropping `input` and `ctx` (they can echo data)."""
    return [
        FieldIssue(
            loc=[*prefix, *(p if isinstance(p, int) else str(p) for p in e.get("loc", ()))],
            msg=str(e.get("msg", "")),
            type=str(e.get("type", "")),
        )
        for e in errors
    ]


class CodedRoute(APIRoute):
    """APIRoute that renders RequestValidationError and RouteError as RouteErrorBody."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def coded_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return RouteError(
                    RouteErrorCode.VALIDATION_ERROR,
                    "Request failed validation; see `errors` for each field.",
                    status_code=422,
                    errors=issues_from(exc.errors()),
                ).response()
            except RouteError as exc:
                return exc.response()

        return coded_handler


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries so generated clients know the error body shape."""
    descriptions = {
        422: "VALIDATION_ERROR or INFEASIBLE_INPUT",
        500: "DATA_INVALID: a data file failed its schema",
        503: "DATA_UNAVAILABLE: a required data file is missing",
    }
    return {code: {"model": RouteErrorBody, "description": descriptions[code]} for code in status_codes}


def read_json(path: Path, display_name: str) -> Any:
    """Parse a data file. `display_name` (relative to the data dir) is used in messages, never the full path."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RouteError(
            RouteErrorCode.DATA_INVALID,
            f"{display_name} is not valid JSON (line {exc.lineno}, column {exc.colno}).",
            status_code=500,
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise RouteError(
            RouteErrorCode.DATA_INVALID,
            f"{display_name} could not be read ({type(exc).__name__}).",
            status_code=500,
        ) from None
